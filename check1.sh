cat > test.sh <<'EOF'
git log --oneline --format="%h %ci %s" -- chroma | head -20
EOF
bash test.sh
