cat > check3.sh <<'EOF'
echo "===== JUNE (c037b4f) ====="
cd /tmp/idx-june && python eval/why.py "What is rnv-color-mcp?"
EOF
bash check3.sh
