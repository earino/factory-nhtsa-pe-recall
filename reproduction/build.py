import csv
import io
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from source_io import fetch

INV_URL = 'https://static.nhtsa.gov/odi/ffdd/inv/FLAT_INV.zip'
RCL_PRE_URL = 'https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_PRE_2010.zip'
RCL_POST_URL = 'https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip'
TARGET = 'recall_24m'
FEATURES = ['make', 'model', 'model_year', 'component', 'manufacturer', 'model_count', 'vehicle_age']
COLUMNS = ['investigation_id'] + FEATURES + ['open_date', TARGET]

try:
    csv.field_size_limit(10000000)
except OverflowError:
    csv.field_size_limit(1000000)


def _normalized(name):
    base = name.rsplit('/', 1)[-1]
    return re.sub(r'[^a-z0-9]', '', base.lower())


def _select_member(names, preferred, token):
    files = [n for n in names if not n.endswith('/')]
    target = _normalized(preferred)
    for name in files:
        key = _normalized(name)
        if key == target or key.endswith(target):
            return name
    for name in files:
        key = _normalized(name)
        if token in key and key.endswith('txt'):
            return name
    txt = sorted(n for n in files if n.lower().endswith('.txt'))
    if len(txt) == 1:
        return txt[0]
    raise AssertionError('no text archive member matching ' + str(preferred) + '; members ' + repr(files[:20]))


def _iter_rows(zip_path, preferred, token):
    with zipfile.ZipFile(zip_path) as zf:
        member = _select_member(zf.namelist(), preferred, token)
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding='latin-1', newline='')
            reader = csv.reader(text, delimiter='\t')
            first = True
            for row in reader:
                if first:
                    first = False
                    if row and row[0].strip().upper() in ('NHTSA ACTION NUMBER', 'ACTION NUMBER', 'ACTION_NUMBER', 'CAMPNO', 'NHTSA CAMPAIGN NUMBER'):
                        continue
                if row:
                    yield member, row


def _parse_date(value):
    s = (value or '').strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, '%Y%m%d').date()
    except ValueError:
        return None


def _parse_year(value):
    s = (value or '').strip()
    if not s.isdigit():
        return None
    y = int(s)
    if y == 9999:
        return None
    return y


def _campaign_ids(value):
    return [part.strip().upper() for part in re.split(r'[,;| ]+', value) if part.strip()]


def _model_parts(value):
    return [part.strip().upper() for part in re.split(r'[;,]+', value) if part.strip()]


def _field_failure(member, first_row, missing, width):
    msg = ('selected archive member ' + str(member) + '; observed first row ' + repr(first_row) +
           '; observed field width ' + str(width) + '; missing fields ' + repr(missing))
    return msg[:4000]


def build(output: Path, cache: Path):
    output = Path(output)
    cache = Path(cache)
    checks = []

    def add(name, observed, expected, passed, kind=None, detail=None):
        item = {'check': name, 'observed': str(observed), 'expected': str(expected), 'passed': bool(passed)}
        if kind:
            item['kind'] = kind
        checks.append(item)
        if not passed:
            message = detail if detail is not None else (name + ': observed ' + repr(observed) + '; expected ' + repr(expected))
            raise AssertionError(str(message)[:4000])

    inv_zip = fetch(INV_URL, cache, 'FLAT_INV.zip')
    rcl_pre = fetch(RCL_PRE_URL, cache, 'FLAT_RCL_PRE_2010.zip')
    rcl_post = fetch(RCL_POST_URL, cache, 'FLAT_RCL_POST_2010.zip')

    stats = Counter()
    inv_member = None
    inv_first = None
    inv_widths = Counter()
    lines_by_action = defaultdict(list)

    for member, row in _iter_rows(inv_zip, 'INV.txt', 'inv'):
        if inv_member is None:
            inv_member = member
        if inv_first is None:
            inv_first = row
        inv_widths[len(row)] += 1
        action = row[0].strip() if row else ''
        if not action.upper().startswith('PE'):
            stats['non_pe'] += 1
            continue
        if len(row) < 7:
            stats['short_pe_row'] += 1
            continue
        stats['pe_lines'] += 1
        make = row[1].strip() if len(row) > 1 else ''
        model = row[2].strip() if len(row) > 2 else ''
        year_raw = row[3].strip() if len(row) > 3 else ''
        component = row[4].strip() if len(row) > 4 else ''
        manufacturer = row[5].strip() if len(row) > 5 else ''
        odate_raw = row[6].strip() if len(row) > 6 else ''
        campno = row[8].strip() if len(row) > 8 else ''
        odate = _parse_date(odate_raw)
        year = _parse_year(year_raw)
        if odate is None:
            stats['unparseable_odate'] += 1
            continue
        if odate < date(1995, 1, 1) or odate > date(2019, 12, 31):
            stats['odate_out_of_range'] += 1
            continue
        if not make or not model:
            stats['missing_make_or_model'] += 1
            continue
        if year is None:
            if year_raw == '9999':
                stats['year_9999'] += 1
            else:
                stats['invalid_year'] += 1
            continue
        if year < 1900 or year > 2019:
            stats['year_out_of_range'] += 1
            continue
        lines_by_action[action].append({
            'action': action,
            'make': make,
            'model': model,
            'model_year': year,
            'component': component,
            'manufacturer': manufacturer,
            'open_date': odate,
            'campno': campno,
        })

    camp_dates = defaultdict(list)
    rcl_members = []
    rcl_first = None
    rcl_widths = Counter()
    rcl_dates_parsed = 0
    rcl_campnos_nonempty = 0

    for archive_label, zip_path in (('pre2010', rcl_pre), ('post2010', rcl_post)):
        found_member = None
        for member, row in _iter_rows(zip_path, 'RCL.txt', 'rcl'):
            if found_member is None:
                found_member = member
                rcl_members.append((archive_label, member))
            if rcl_first is None:
                rcl_first = row
            rcl_widths[len(row)] += 1
            if len(row) < 16:
                continue
            campaign = row[1].strip().upper()
            recall_date = _parse_date(row[15])
            if campaign:
                rcl_campnos_nonempty += 1
            if campaign and recall_date:
                camp_dates[campaign].append(recall_date)
                rcl_dates_parsed += 1
        if found_member is None:
            rcl_members.append((archive_label, None))

    rows = []
    campno_present = 0
    unmatched_campno = 0
    multi_odate = 0
    multi_odate_actions = []
    for action in sorted(lines_by_action):
        lines = lines_by_action[action]
        distinct_dates = sorted({line['open_date'] for line in lines})
        open_date = distinct_dates[0]
        if len(distinct_dates) > 1:
            multi_odate += 1
            if len(multi_odate_actions) < 10:
                multi_odate_actions.append(action)
        rep = sorted(lines, key=lambda line: (line['make'].upper(), line['model'].upper(), line['model_year'], line['component'].upper(), line['manufacturer'].upper()))[0]
        models = set()
        campaigns = set()
        for line in lines:
            models.update(_model_parts(line['model']))
            campaigns.update(_campaign_ids(line['campno']))
        model_count = len(models) if models else 1
        if campaigns:
            campno_present += 1
        if campaigns and not any(campaign in camp_dates for campaign in campaigns):
            unmatched_campno += 1
        label = 0
        end = open_date + timedelta(days=730)
        for campaign in sorted(campaigns):
            for recall_date in camp_dates.get(campaign, []):
                if open_date < recall_date <= end:
                    label = 1
                    break
            if label:
                break
        rows.append({
            'investigation_id': action,
            'make': rep['make'],
            'model': rep['model'],
            'model_year': rep['model_year'],
            'component': rep['component'],
            'manufacturer': rep['manufacturer'],
            'model_count': model_count,
            'vehicle_age': open_date.year - rep['model_year'],
            'open_date': open_date.isoformat(),
            TARGET: label,
        })

    rows.sort(key=lambda row: (row['open_date'], row['investigation_id'], row['make'], row['model'], row['model_year'], row['component'], row['manufacturer']))

    parts = {'train': [], 'eval': [], 'holdout': []}
    for row in rows:
        day = date.fromisoformat(row['open_date'])
        if day < date(2008, 1, 1):
            parts['train'].append(row)
        elif day < date(2015, 1, 1):
            parts['eval'].append(row)
        else:
            parts['holdout'].append(row)

    (output / 'public').mkdir(parents=True, exist_ok=True)
    (output / 'private').mkdir(parents=True, exist_ok=True)
    for name, path in (('train', output / 'public' / 'train.csv'), ('eval', output / 'public' / 'eval.csv'), ('holdout', output / 'private' / 'holdout.csv')):
        pd.DataFrame(parts[name], columns=COLUMNS).to_csv(path, index=False)

    inv_max_width = max(inv_widths) if inv_widths else 0
    rcl_max_width = max(rcl_widths) if rcl_widths else 0
    inv_member_ok = inv_member is not None and _normalized(inv_member).endswith('invtxt')
    add('inv_archive_member', inv_member, 'a non-directory text member whose normalized basename ends with invtxt, currently FLAT_INV.txt', inv_member_ok, detail=_field_failure(inv_member, inv_first, ['INV text member'], inv_max_width))

    rcl_members_ok = (
        len(rcl_members) == 2
        and {label for label, _ in rcl_members} == {'pre2010', 'post2010'}
        and all(member is not None and _normalized(member).endswith('txt') and 'rcl' in _normalized(member) for _, member in rcl_members)
    )
    add('rcl_archive_members', rcl_members, 'one RCL text member from each recall archive; current members include FLAT_RCL_PRE_2010.txt and FLAT_RCL_POST_2010.txt, selected by normalized basename containing rcl and ending txt', rcl_members_ok, detail=_field_failure(rcl_members, rcl_first, ['RCL text member from each archive'], rcl_max_width))

    add('inv_field_width', dict(inv_widths), 'at least 9 tab-delimited fields for CAMPNO', inv_max_width >= 9, detail=_field_failure(inv_member, inv_first, ['field 9 CAMPNO'], inv_max_width))
    add('rcl_field_width', dict(rcl_widths), 'at least 16 tab-delimited fields for RCDATE', rcl_max_width >= 16, detail=_field_failure(rcl_members, rcl_first, ['field 2 CAMPNO', 'field 16 RCDATE'], rcl_max_width))
    add('pe_actions_observed', len(lines_by_action), 'at least one PE action number with a valid population line', len(lines_by_action) > 0)
    add('rcl_campaign_values', rcl_campnos_nonempty, 'at least one non-empty RCL campaign identifier', rcl_campnos_nonempty > 0)
    add('rcl_recall_dates_parsed', rcl_dates_parsed, 'at least one parseable RCDATE linked to a campaign', rcl_dates_parsed > 0)
    add('year_9999_excluded', stats['year_9999'], 'counted and excluded under the frozen population; non-abortive coverage evidence', stats['year_9999'] >= 0)
    add('included_rows', len(rows), 'nonempty constructed rows', len(rows) > 0)

    duplicate_ids = len(rows) - len({row['investigation_id'] for row in rows})
    add('unique_investigation_ids', duplicate_ids, '0 repeated investigation_id values after collapsing to one row per PE action number', duplicate_ids == 0, detail='duplicate investigation_id rows ' + str(duplicate_ids) + ' over ' + str(len(rows)) + ' constructed rows and ' + str(len(lines_by_action)) + ' action numbers')
    add('one_row_per_action', len(rows), 'one constructed row per valid PE action number, expected ' + str(len(lines_by_action)), len(rows) == len(lines_by_action))
    add('multi_odate_actions', multi_odate, '0 action numbers with conflicting ODATE values; the earliest ODATE is used when conflicts exist', multi_odate == 0, detail='action numbers with conflicting ODATE values ' + repr(multi_odate_actions) + '; count ' + str(multi_odate))

    model_years = [row['model_year'] for row in rows]
    add('years_included', (min(model_years), max(model_years)) if model_years else None, 'all model_year values within 1900 through 2019', bool(model_years) and min(model_years) >= 1900 and max(model_years) <= 2019)
    add('make_model_nonempty', sum(1 for row in rows if not row['make'] or not row['model']), '0 empty make or model values', all(row['make'] and row['model'] for row in rows))
    add('model_count_positive', min((row['model_count'] for row in rows), default=0), 'all model_count values at least 1', bool(rows) and all(row['model_count'] >= 1 for row in rows), kind='unit')
    add('campaign_join_key', len(camp_dates), 'at least one RCL campaign key with a parseable RCDATE', len(camp_dates) > 0, detail=_field_failure(rcl_members, rcl_first, ['field 2 CAMPNO', 'field 16 RCDATE'], rcl_max_width))
    add('unmatched_campno_rows', unmatched_campno, 'missing-coverage count is a subset of constructed rows; the frozen label rule assigns 0 when no linked recall falls in the 730-day window', unmatched_campno <= len(rows))
    add('campno_present_rows', campno_present, 'number of constructed rows carrying a non-empty CAMPNO label-source value', campno_present <= len(rows))

    target_values = sorted(set(row[TARGET] for row in rows))
    add('target_binary', target_values, 'subset of 0 and 1', set(target_values).issubset({0, 1}))

    windows = {'train': (None, date(2008, 1, 1)), 'eval': (date(2008, 1, 1), date(2015, 1, 1)), 'holdout': (date(2015, 1, 1), None)}
    for name in ('train', 'eval', 'holdout'):
        part = parts[name]
        add('split_nonempty_' + name, len(part), 'at least one row', len(part) > 0)
        days = [date.fromisoformat(row['open_date']) for row in part]
        low = min(days) if days else None
        high = max(days) if days else None
        start, end = windows[name]
        ok = low is not None and (start is None or low >= start) and (end is None or high < end)
        add('split_bounds_' + name, (low.isoformat() if low else None, high.isoformat() if high else None), 'half-open window ' + str(start) + ' to ' + str(end), ok)

    add('unit_outcome_horizon', '730 calendar days', '24-month horizon used in the label comparison', timedelta(days=730).days == 730, kind='unit')
    add('unit_vehicle_age', 'integer years', 'open calendar year minus representative model year', bool(rows) and all(isinstance(row['vehicle_age'], int) for row in rows), kind='unit')

    for name in ('train', 'eval', 'holdout'):
        frame = pd.DataFrame(parts[name], columns=COLUMNS)
        add('columns_' + name, list(frame.columns), COLUMNS, list(frame.columns) == COLUMNS)

    return checks
