"""Read-only combined asset/scene queries; row identity never depends on the icon."""
import os
from ..config import commonSetting, databaseHost

TABLE_FOLDERS = {'asset': 'Assets', 'scene': 'Scenes'}
FIELDS = {
    'asset': ('date','name','zh_name','mod_artist','mod_status','rig_artist','rig_status','icon','note','ue_status','ue_artist'),
    'scene': ('date','name','zh_name','artist','status','artist','status','icon','note','ue_status','ue_artist'),
}

def metadata(row):
    return row[11] if len(row)>11 and isinstance(row[11],dict) and row[11].get('library_row') else {}

def identity(row):
    meta=metadata(row)
    return (meta.get('project'),meta.get('table'),meta.get('type'),str(row[1]))

def tag_row(row,project,table,record_type,root):
    values=list(row[:11])
    if table=='scene':
        values[5:7]=['','']  # Scenes have no independent rig artist/status.
    values.append(dict(library_row=True,project=project,table=table,type=record_type,
        root=os.path.join(str(root),project,TABLE_FOLDERS[table],record_type,str(row[1]))))
    return tuple(values)

def accepts(scope,table,record_type):
    return scope[0] in ('all',table) and (scope[1] is None or scope[1]==record_type)

def discover_types(settings,project):
    result={}
    for table,folder in TABLE_FOLDERS.items():
        try:
            with os.scandir(os.path.join(str(settings['rootPath']),project,folder)) as entries:
                names=sorted((e.name for e in entries if not e.name.startswith('.') and e.is_dir()),key=str.casefold)
        except OSError:
            names=[]
        if not names and table=='asset':
            names=list(settings.get('type') or ['Characters','Props'])
        result[table]=names
    return result

def query_rows(user,password,project,scope,settings):
    import psycopg2
    conn=cur=None
    try:
        conn=psycopg2.connect(database=project,user=user,password=password,host=databaseHost(settings),
            port='5432',connect_timeout=4,options='-c statement_timeout=12000')
        cur=conn.cursor()
        rows=[]
        for table,fields in FIELDS.items():
            if scope[0] not in ('all',table):
                continue
            columns=', '.join('"{0}.{1}"'.format(table,f) for f in fields+('type',))
            query='SELECT {0} FROM public."{1}"'.format(columns,table)
            args=()
            if scope[1] is not None:
                query+=' WHERE "{0}.type" = %s'.format(table)
                args=(scope[1],)
            cur.execute(query,args)
            for row in cur.fetchall():
                rows.append(tag_row(row,project,table,str(row[11]),settings['rootPath']))
        return rows
    finally:
        if cur is not None: cur.close()
        if conn is not None: conn.close()
