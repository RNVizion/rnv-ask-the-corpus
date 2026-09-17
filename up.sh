git pull && python scripts/ingest.py && python eval/check_index_coverage.py --strict && git add chroma && git commit -m "corpus: index honest-and-wrong and the-warning-not-the-gate" && git push
