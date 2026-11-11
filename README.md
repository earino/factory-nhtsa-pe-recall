---
license: other
license_name: upstream-terms-preserved
license_link: LICENSE.md
task_categories:
- tabular-classification
configs:
- config_name: default
  data_files:
  - split: train
    path: extract/public/train.csv
  - split: validation
    path: extract/public/eval.csv
  - split: test
    path: extract/private/holdout.csv
---

<!-- dataset-factory:links -->
**Dataset Factory · v-76d064ad7e164c41**

[Dataset website](https://earino.github.io/factory-nhtsa-pe-recall/versions/v-76d064ad7e164c41/) · [GitHub release](https://github.com/earino/factory-nhtsa-pe-recall/releases/tag/v-76d064ad7e164c41) · [Hugging Face](https://huggingface.co/datasets/earino/factory-nhtsa-pe-recall/tree/v-76d064ad7e164c41) · [Catalogue](https://earino.github.io/dataset-factory-site/)

Artifact: 7119c52b6fe5171677a06aebffca01b29a9960e1d0534755b8126137bbcf82ef
<!-- /dataset-factory:links -->

# Will a newly opened NHTSA preliminary evaluation produce a safety recall within 24 months?

Will a newly opened NHTSA preliminary evaluation (PE) into a vehicle defect result in a linked safety recall campaign within 24 months?

Derived from National Highway Traffic Safety Administration (NHTSA). This is not its official product.

Prediction time: The PE open date (ODATE), before investigation findings, closure, or a recall campaign number are known.

Evaluation scope: `retrospective_research`. Public validation is development data. The downloadable labeled holdout is public; it is not cryptographically sealed. No final holdout benchmark score is claimed.

## Measured baseline

The existing runner was used unchanged on public validation. See `evaluation.json` for rows, controls, per-year results and limitations.

```json
{
  "full_model": {
    "auc": 0.6195033955857386,
    "brier": 0.25882025409720283
  },
  "majority_prior": {
    "auc": 0.5,
    "brier": 0.27862388536640176
  },
  "calendar_identity": {
    "auc": 0.5046264855687607,
    "brier": 0.28067643525720437
  }
}
```

## Limitations

- Current-vintage retrospective snapshot: the 2026 ODI file may reflect later corrections and does not prove the fields were operationally available in real time during 1995-2019.
- CAMPNO attribution is imperfect: one recall may be linked to multiple PEs or models, and a PE may be followed by an EA; using PE only reduces but does not eliminate shared-event dependence.
- Recall timing uses RCDATE from the recall file; if CAMPNO is present but unmatched or RCDATE is missing, the row is labeled 0, which can understate escalation.
- Territorial limit: Public Domain U.S. Government status rests on 17 U.S.C. § 105 and does not establish worldwide public domain; manufacturer names and trademarks remain third-party.
- No production or sales exposure; recall propensity is not normalized by fleet size.
- YEAR=9999 is used to exclude equipment, tire, and child-restraint records, but some vehicle PEs with unknown model years are dropped.
- Multiple make/model lines sharing one NHTSA action number are collapsed to one row per PE; the deterministic representative line discards within-PE variation in make, model, model year, component, and manufacturer.
- Recall timing uses RCDATE from the recall file; if CAMPNO is present but unmatched or RCDATE is missing, the row is labeled 0 under the frozen rule, which can understate escalation.
- Territorial limit: Public Domain U.S. Government status rests on 17 U.S.C. 105 and does not establish worldwide public domain; manufacturer names and trademarks remain third-party.
- YEAR 9999 is used to exclude equipment, tire, and child-restraint records, but some vehicle PEs with unknown model years are dropped.
- MODEL delimiter interpretation is assumed; if the source uses a different list separator, model_count may undercount or overcount.
- No full-row availability ledger exists, so training_label_timing is unverified and feature availability is documented-field evidence plus explicit assumptions.
- No uncertainty interval; observed differences do not establish universal headroom

## Loading and reproduction

Verify all downloaded files with `verify_dataset.py`. CSV splits live under `extract/`; `meta.json` declares the target and identifiers. `MANIFEST.json` binds data, source snapshot, code and measured evidence.

To reconstruct without network source drift, extract `source-snapshot.tar.gz` into a new cache directory, install `reproduction/requirements.txt` in an isolated Python environment, then run `python reproduction/dataset_run.py --output NEW_EMPTY_DIRECTORY --source-cache CACHE_DIRECTORY`. Compare the qualification artifact digest with this manifest. This performs full validation and baseline evaluation and may need worker resources.

See `LICENSE.md` for source terms and preserved attribution.
