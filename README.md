# CIVORA

CIVORA is the canonical runtime for the LOCAL NEWS V2 evidence, verification and editorial pipeline.

## Current repository baseline

This branch imports the latest locally available validated source package: `CIVORA core runtime v0.2`. The more recent conversational checkpoints remain to be consolidated into repository commits from their verified artifact packages.

## Validation

```bash
python -m unittest discover -s tests -v
```

## Workflow

Changes are developed on branches, validated by GitHub Actions and merged through pull requests.
