git log --oneline --date=short --pretty='%h %ad %s' -- chroma/ | head -20

git log --oneline --date=short --pretty='%h %ad %s' -S'fit-over-default' -- sources.json
