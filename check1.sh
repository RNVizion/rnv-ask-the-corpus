cd /workspaces/rnv-ask-the-corpus
git worktree prune
git worktree add /tmp/idx-june c037b4f

cd /tmp/idx-june && python -c "
import chromadb
c=chromadb.PersistentClient(path='chroma').get_collection('corpus')
d=c.get()
for i,doc in zip(d['ids'],d['documents']):
    if i.startswith('resume'):
        print(i, len(doc.split()), 'HAS-MCP' if 'color-mcp' in doc else 'no')
"
