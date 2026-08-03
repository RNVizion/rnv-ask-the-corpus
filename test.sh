python -c "
import chromadb
c=chromadb.PersistentClient(path='chroma')
n=[x.name for x in c.list_collections()]; print('collections:',n)
col=c.get_collection(n[0]); g=col.get(include=['documents'])
for i,d in zip(g['ids'],g['documents']):
    if 'design goal' in d.lower(): print('HOLDS IT:',i,'| chars:',len(d))
"
