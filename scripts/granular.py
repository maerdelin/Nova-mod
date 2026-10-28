#!/usr/bin/env python3
"""Instruction/field/XML-property patches; never copy an old DEX or class.

A patch is applied transactionally to a freshly decoded upstream APK. Context
and symbolic-reference checks fail closed on ambiguous/incompatible changes.
No arbitrary-future-version compatibility or whole-program equivalence claim.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ANDROID = 'http://schemas.android.com/apk/res/android'
ET.register_namespace('android', ANDROID)
ET.register_namespace('app', 'http://schemas.android.com/apk/res-auto')
ID = '{' + ANDROID + '}id'
LABEL = re.compile(r'(?<![\w;\"\'])\:[A-Za-z_][A-Za-z0-9_]*')
METHOD = re.compile(r'^\.method [^\n]+\n.*?^\.end method', re.M | re.S)
RESOURCE = re.compile(r'(?<![\w])-?0x[0-9a-fA-F]{8}(?![\w])')
SYMBOL = re.compile(r'\$\{RES:([^}]+)\}')
QUOTED = re.compile(r'("(?:\\.|[^"\\])*")')
FORMAT = 'nova-granular-v1'

class Conflict(RuntimeError):
    pass

def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def resource_map(root: Path) -> dict[str, str]:
    path = root / 'res/values/public.xml'
    if not path.exists():
        raise Conflict('Decoded resource symbol table is missing')
    return {x.attrib['id'].lower(): x.attrib['type'] + '/' + x.attrib['name']
            for x in ET.parse(path).getroot() if x.tag == 'public'}

def outside_strings(line: str, transform) -> str:
    return ''.join(piece if i % 2 else transform(piece)
                   for i, piece in enumerate(QUOTED.split(line)))

def clean(line: str) -> str:
    pieces = QUOTED.split(line)
    for i in range(0, len(pieces), 2):
        if '#' in pieces[i]:
            pieces[i] = pieces[i].split('#', 1)[0]
            pieces = pieces[:i+1]
            break
    return ''.join(pieces).strip()

def tokens(text: str, symbols: dict[str, str]) -> list[str]:
    result = []
    for line in text.splitlines():
        line = clean(line)
        if not line or line == 'nop':
            continue
        if line.startswith('.field ') and ' static ' in line:
            line = re.sub(r' = (?:false|null|0x0L?|0\.0f?)$', '', line)
        line = outside_strings(line, lambda s: RESOURCE.sub(
            lambda m: '${RES:' + symbols[m[0].lower()] + '}' if m[0].lower() in symbols else m[0], s))
        if re.match(r'const/high16 [vp]\d+, \$\{RES:', line):
            line = line.replace('const/high16 ', 'const ', 1)
        result.append(line)
    return result

def materialize(lines: list[str], symbols: dict[str, str]) -> str:
    reverse = {v: k for k, v in symbols.items()}
    def replace(m):
        if m[1] not in reverse:
            raise Conflict('Missing upstream resource: ' + m[1])
        return reverse[m[1]]
    return '\n'.join(outside_strings(line, lambda s: SYMBOL.sub(replace, s)) for line in lines)

def split_methods(text: str):
    found = {}
    remainder = []; last = 0
    for match in METHOD.finditer(text):
        name = match[0].splitlines()[0].split()[-1]
        if name in found:
            raise Conflict('Duplicate method: ' + name)
        found[name] = match
        remainder.append(text[last:match.start()]); last = match.end()
    remainder.append(text[last:])
    return found, ''.join(remainder)

def label_replace(line: str, mapping: dict[str, str]) -> str:
    return outside_strings(line, lambda s: LABEL.sub(lambda m: mapping.get(m[0], m[0]), s))

def shape_data(lines: list[str]):
    keys = []; labels = {}; in_payload = False
    for line in lines:
        if line.startswith(('.packed-switch ', '.sparse-switch', '.array-data ')):
            in_payload = True
        if line.startswith(('.end packed-switch', '.end sparse-switch', '.end array-data')):
            in_payload = False
        if line.startswith(':') and not in_payload:
            if not LABEL.fullmatch(line) or line in labels:
                raise Conflict('Malformed/duplicate label: ' + line)
            labels[line] = len(keys)
        else:
            keys.append(digest(label_replace(line, {m[0]: ':LABEL' for m in LABEL.finditer(line)})))
    return keys, labels

def project(lines: list[str], base_keys: list[str], base_labels: dict[str, int], prefix: str):
    keys, labels = shape_data(lines)
    correspond = {}
    for block in difflib.SequenceMatcher(None, base_keys, keys, autojunk=False).get_matching_blocks():
        for d in range(block.size):
            correspond[block.b+d] = block.a+d
    mapping = {}; used = set()
    for label, position in labels.items():
        if label.startswith(':nova_'):
            mapping[label] = label; continue
        old_pos = correspond.get(position)
        possible = [s for s, pos in base_labels.items() if pos == old_pos and s not in used]
        kind = label.split('_')[0]
        same_kind = [s for s in possible if s.split('_')[0] == kind]
        if label in same_kind:
            chosen = label
        elif len(same_kind) == 1:
            chosen = same_kind[0]
        elif len(possible) == 1:
            chosen = possible[0]
        else:
            chosen = ':' + prefix + '_' + str(len(mapping))
        mapping[label] = chosen; used.add(chosen)
    if len(set(mapping.values())) != len(mapping):
        raise Conflict('Ambiguous label correspondence')
    return [label_replace(line, mapping) for line in lines], {v: k for k, v in mapping.items()}

def hunks(before: list[str], after: list[str]) -> list[dict]:
    result = []
    for tag, i, j, x, y in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        result.append({'before': before[i:j], 'after': after[x:y],
                       'left': before[max(0, i-8):i], 'right': before[j:j+8],
                       'after_left': after[max(0, x-8):x], 'after_right': after[y:y+8]})
    return result

def occurrences(lines: list[str], pattern: list[str]) -> list[int]:
    if not pattern:
        raise Conflict('Empty patch anchor')
    return [i for i in range(len(lines)-len(pattern)+1) if lines[i:i+len(pattern)] == pattern]

def locate(lines: list[str], hunk: dict, after=False) -> list[int]:
    left = hunk['after_left'] if after else hunk['left']
    right = hunk['after_right'] if after else hunk['right']
    body = hunk['after'] if after else hunk['before']
    matches = [i+len(left) for i in occurrences(lines, left+body+right)]
    if matches:
        return matches
    # Preserve every original before/after instruction body. Accept reduced
    # context only if the full body is anchored at precisely one location.
    for cap in (7, 6, 5, 4, 3, 2):
        lpart = left[-cap:] if left else []
        rpart = right[:cap]
        if len(lpart) + len(rpart) < 4:
            continue
        candidates = [i+len(lpart) for i in occurrences(lines, lpart+body+rpart)]
        if len(candidates) == 1:
            return candidates
        if len(candidates) > 1:
            raise Conflict('Ambiguous v6.6 reduced-context hunk')
    return []

def apply_hunks(lines: list[str], changes: list[dict]):
    old_hits = [locate(lines, h) for h in changes]
    if all(len(hit) == 1 for hit in old_hits):
        edits = [(hit[0], hit[0]+len(h['before']), h['after']) for hit,h in zip(old_hits,changes)]
        edits.sort(key=lambda e: (e[0], e[1]))
        for a,b in zip(edits, edits[1:]):
            if a[1] > b[0] or a[0] == b[0]:
                raise Conflict('Overlapping instruction edits')
        result = list(lines)
        for start,end,replacement in reversed(edits):
            result[start:end] = replacement
        return result, 'applied'
    if all(len(locate(lines,h,True)) == 1 for h in changes):
        return lines, 'already-applied'
    details = [i for i, hit in enumerate(old_hits) if len(hit) != 1]
    raise Conflict('Instruction context missing/ambiguous at hunks ' + str(details))

def register_line(lines: list[str]):
    result = [x for x in lines if x.startswith(('.locals ', '.registers '))]
    if len(result) > 1:
        raise Conflict('Multiple register declarations')
    return result[0] if result else None

def check_labels(lines: list[str]):
    _, label_positions = shape_data(lines)
    defs = set(label_positions)
    refs = set()
    for x in lines:
        outside_strings(x, lambda s: (refs.update(m[0] for m in LABEL.finditer(s)) or s))
    if not refs.issubset(defs):
        raise Conflict('Unresolved branch labels: ' + str(sorted(refs-defs)))

def xml_key(node: ET.Element):
    if ID in node.attrib:
        return ID, node.attrib[ID]
    if 'name' in node.attrib:
        return 'name', node.attrib['name']
    return None

def xml_selector(root: ET.Element, node: ET.Element, path: list[dict]):
    key = xml_key(node)
    if key and sum(x.tag == node.tag and x.attrib.get(key[0]) == key[1] for x in root.iter()) == 1:
        return {'tag': node.tag, 'key': list(key)}
    return {'path': path}

def xml_target(root: ET.Element, selector: dict):
    if 'key' in selector:
        k,v=selector['key']; items=[x for x in root.iter() if x.tag==selector['tag'] and x.attrib.get(k)==v]
        if len(items)!=1:
            raise Conflict('XML target missing/ambiguous: '+str(selector))
        return items[0]
    node=root
    for n,step in enumerate(selector['path']):
        if n==0:
            if node.tag!=step['tag']:raise Conflict('XML root changed')
            continue
        children=[x for x in node if x.tag==step['tag']]
        if 'key' in step:
            k,v=step['key']; children=[x for x in children if x.attrib.get(k)==v]
            if len(children)!=1:raise Conflict('XML path key missing/ambiguous')
            node=children[0]
        else:
            if len(children)!=step['count']:raise Conflict('Unnamed XML sibling structure changed')
            node=children[step['index']]
    return node

def node_text(node):
    return node.text or ''

def xml_changes(old: ET.Element, new: ET.Element) -> list[dict]:
    result=[]
    def visit(a,b,path):
        if a.tag!=b.tag:raise Conflict('Element type edit needs an explicit rule')
        select=xml_selector(old,a,path)
        for key in sorted(a.attrib.keys()|b.attrib.keys()):
            if a.attrib.get(key)!=b.attrib.get(key):
                result.append({'selector':select,'kind':'attribute','key':key,'before':a.attrib.get(key),'after':b.attrib.get(key)})
        if (node_text(a).strip() if len(a) else node_text(a)) != (node_text(b).strip() if len(b) else node_text(b)):
            result.append({'selector':select,'kind':'text','before':node_text(a),'after':node_text(b)})
        if a.tag.endswith('-array') and all(x.tag=='item' and not len(x) and not x.attrib for x in list(a)+list(b)):
            aa=[node_text(x) for x in a];bb=[node_text(x) for x in b]
            if aa!=bb:
                if sorted(aa)!=sorted(bb):raise Conflict('Array additions need explicit review')
                result.append({'selector':select,'kind':'array-order','before':aa,'after':bb})
            return
        if len(a)!=len(b):raise Conflict('Structural node insertion/removal needs an explicit rule')
        for i,(x,y) in enumerate(zip(a,b)):
            if xml_key(x)!=xml_key(y):raise Conflict('Child identity changed; refusing positional replacement')
            step={'tag':x.tag}
            if key:=xml_key(x):step['key']=list(key)
            else:
                step['index']=sum(z.tag==x.tag for z in list(a)[:i]);step['count']=sum(z.tag==x.tag for z in a)
            visit(x,y,path+[step])
    visit(old,new,[{'tag':old.tag}])
    return result

def apply_xml(root: ET.Element, edits: list[dict]):
    counts={'applied':0,'already-applied':0}
    for edit in edits:
        node=xml_target(root,edit['selector']);kind=edit['kind']
        if kind=='attribute':current=node.attrib.get(edit['key'])
        elif kind=='text':current=node_text(node)
        elif kind=='array-order':current=[node_text(x) for x in node]
        else:raise Conflict('Unsupported XML patch operation')
        if current==edit['after']:
            counts['already-applied']+=1;continue
        if current!=edit['before']:
            raise Conflict('XML precondition conflict: '+str(edit['selector'])+' '+str(edit.get('key',kind)))
        if kind=='attribute':
            if edit['after'] is None:node.attrib.pop(edit['key'],None)
            else:node.set(edit['key'],edit['after'])
        elif kind=='text':node.text=edit['after']
        else:
            by_text={node_text(x):x for x in node}
            if len(by_text)!=len(node):raise Conflict('Nonunique array entries')
            node[:]=[by_text[v] for v in edit['after']]
        counts['applied']+=1
    return counts

def class_index(root: Path):
    result={}
    for top in root.glob('smali*'):
        if not top.is_dir():continue
        for path in top.rglob('*.smali'):
            desc='L'+path.relative_to(top).as_posix()[:-6]+';'
            if desc in result:raise Conflict('Duplicate class '+desc)
            result[desc]=path
    return result

def class_header(text: str):
    return [clean(x) for x in text.splitlines() if x.startswith(('.class ','.super ','.implements '))]

MEMBER = re.compile(r'(L[^\s;]+;)->([^\s,}]+)')

def member_available(owner, member, index, pending, seen=None):
    seen=set() if seen is None else seen
    if owner in seen:return False
    seen.add(owner)
    if owner not in index:
        return owner not in ('Ljava/lang/Object;',)
    path=index[owner];text=pending.get(path,path.read_text())
    methods,_=split_methods(text)
    if '(' in member and member in methods:return True
    if '(' not in member:
        for line in text.splitlines():
            line=clean(line)
            if line.startswith('.field ') and line.split(' = ')[0].split()[-1]==member:return True
    parents=[x.split()[-1] for x in class_header(text) if x.startswith(('.super ','.implements '))]
    return any(member_available(x,member,index,pending,seen) for x in parents)

def patch_dependencies(patch, index):
    found=set()
    for method in patch['methods']:
        for h in method['hunks']:
            for line in h['after']:
                def collect(piece):
                    found.update((m[1],m[2]) for m in MEMBER.finditer(piece) if m[1] in index)
                    return piece
                outside_strings(line,collect)
    return [{'class':a,'member':b} for a,b in sorted(found)]

def extract(old: Path, new: Path, output: Path):
    so=resource_map(old);sn=resource_map(new)
    ao=class_index(old);an=class_index(new)
    if ao.keys()!=an.keys():raise Conflict('Added/removed classes require explicit review')
    patch={'format':FORMAT,'origin':'Official Nova 6.5.5 -> user-tested V9.8.2',
           'whole_file_replacements':False,'methods':[],'fields':[],'xml':[]}
    for name in sorted(ao):
        a=ao[name].read_text();b=an[name].read_text()
        if a==b:continue
        ma,oa=split_methods(a);mb,ob=split_methods(b)
        if ma.keys()!=mb.keys():raise Conflict('Added/removed methods require explicit review: '+name)
        if class_header(a)!=class_header(b):raise Conflict('Class inheritance changed: '+name)
        if tokens(oa,so)!=tokens(ob,sn):
            fields_a={x.split(' = ')[0].split()[-1]:x for x in tokens(oa,so) if x.startswith('.field ')}
            fields_b={x.split(' = ')[0].split()[-1]:x for x in tokens(ob,sn) if x.startswith('.field ')}
            if fields_a.keys()!=fields_b.keys():raise Conflict('Field set changed')
            for field in sorted(fields_a):
                if fields_a[field]!=fields_b[field]:
                    patch['fields'].append({'class':name,'field':field,'before':fields_a[field],'after':fields_b[field]})
            only=lambda ls:[x for x in ls if not x.startswith('.field ')]
            if only(tokens(oa,so))!=only(tokens(ob,sn)):raise Conflict('Unclassified class metadata change: '+name)
        for method in sorted(ma):
            aa=tokens(ma[method][0],so);bb=tokens(mb[method][0],sn)
            if aa==bb:continue
            keys,labels=shape_data(aa)
            bb,_=project(bb,keys,labels,'nova_'+digest(name+method)[:10])
            changes=hunks(aa,bb)
            if not changes:continue
            check_labels(bb)
            patch['methods'].append({'class':name,'method':method,'class_header':class_header(a),
                'registers_before':register_line(aa),'registers_after':register_line(bb),
                'shape_hashes':keys,'labels':labels,'hunks':changes,
                'baseline_before_sha256':digest('\n'.join(aa)), 'baseline_after_sha256':digest('\n'.join(bb))})
    paths={p.relative_to(old).as_posix() for p in old.rglob('*.xml') if p.relative_to(old).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    new_paths={p.relative_to(new).as_posix() for p in new.rglob('*.xml') if p.relative_to(new).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    if paths!=new_paths:raise Conflict('Added/removed XML resources need explicit review')
    for path in sorted(paths):
        a=old/path;b=new/path
        if a.read_bytes()==b.read_bytes():continue
        if path=='res/values/public.xml':raise Conflict('Baseline resource IDs changed; explicit review required')
        edits=xml_changes(ET.parse(a).getroot(),ET.parse(b).getroot())
        if edits:patch['xml'].append({'path':path,'edits':edits})
    patch['dependencies']=patch_dependencies(patch,ao)
    patch['stats']={'classes':len(set(x['class'] for x in patch['methods']+patch['fields'])),
                    'methods':len(patch['methods']),'instruction_hunks':sum(len(x['hunks']) for x in patch['methods']),
                    'field_declarations':len(patch['fields']),'xml_files':len(patch['xml']),
                    'xml_operations':sum(len(x['edits']) for x in patch['xml']),
                    'removed_tokens':sum(len(h['before']) for m in patch['methods'] for h in m['hunks']),
                    'inserted_tokens':sum(len(h['after']) for m in patch['methods'] for h in m['hunks'])}
    write_json(output,patch);print(json.dumps(patch['stats'],indent=2))
    return patch

def apply(root: Path, patch: dict, report: Path | None=None):
    if patch.get('format')!=FORMAT or patch.get('whole_file_replacements') is not False:
        raise Conflict('Not a supported granular-only patch')
    symbols=resource_map(root);index=class_index(root);pending={};statuses=[]
    def content(desc):
        if desc not in index:raise Conflict('Target class missing: '+desc)
        path=index[desc]
        return path,pending.get(path,path.read_text())
    for field in patch['fields']:
        path,text=content(field['class']);ls=text.splitlines();hit=[i for i,x in enumerate(ls) if clean(x) in (field['before'],field['after'])]
        if len(hit)!=1:raise Conflict('Field conflict: '+field['class']+'->'+field['field'])
        status='already-applied' if clean(ls[hit[0]])==field['after'] else 'applied'
        ls[hit[0]]=field['after'];pending[path]='\n'.join(ls)+'\n'
        statuses.append({'class':field['class'],'field':field['field'],'status':status})
    for rule in patch['methods']:
        path,text=content(rule['class']);methods,_=split_methods(text)
        if rule['method'] not in methods:raise Conflict('Target method missing: '+rule['class']+'->'+rule['method'])
        if class_header(text)!=rule['class_header']:raise Conflict('Class hierarchy changed: '+rule['class'])
        match=methods[rule['method']];original=tokens(match[0],symbols)
        if register_line(original) not in (rule['registers_before'],rule['registers_after']):
            raise Conflict('Register allocation changed: '+rule['class']+'->'+rule['method'])
        projected,inverse=project(original,rule['shape_hashes'],rule['labels'],'upstream')
        changes=rule['hunks']
        # v6.6 R8 changed this callback argument's obfuscated interface name
        # from Lhs1; to Ljs1;. The entire old onMenuItemSelected body is
        # removed by the existing patch. Require the new descriptor in the
        # current method; do not relax method identity or remove the edit.
        if rule['class'] == 'Lcom/archos/mediacenter/video/browser/filebrowsing/BrowserByVideoFolder$1;' and rule['method'] == 'onMenuItemSelected(Landroid/view/MenuItem;)Z':
            import copy
            changes=copy.deepcopy(changes)
            for h in changes:
                h['before']=[s.replace('Ln4;->a(Ljava/lang/Object;Lhs1;)V',
                                        'Ln4;->a(Ljava/lang/Object;Ljs1;)V') for s in h['before']]
        try:
            edited,status=apply_hunks(projected,changes)
        except Conflict as e:
            print('NOVA_V66_GRANULAR_CONFLICT_CLASS=' + rule['class'], flush=True)
            print('NOVA_V66_GRANULAR_CONFLICT_METHOD=' + rule['method'], flush=True)
            for i, line in enumerate(projected):
                print('NOVA_V66_METHOD[%03d] %s' % (i, line), flush=True)
            for i, hunk in enumerate(rule['hunks']):
                print('NOVA_V66_HUNK[%d] before=%r after=%r' % (i, hunk['before'], hunk['after']), flush=True)
            raise Conflict(rule['class']+'->'+rule['method']+': '+str(e)) from e
        restored=[label_replace(line,inverse) for line in edited]
        check_labels(restored)
        replacement=materialize(restored,symbols)
        pending[path]=text[:match.start()]+replacement+text[match.end():]
        statuses.append({'class':rule['class'],'method':rule['method'],'status':status,'hunks':len(rule['hunks'])})
    for rule in patch['xml']:
        path=root/rule['path']
        if not path.is_file():raise Conflict('Resource missing: '+rule['path'])
        element=ET.fromstring(path.read_text())
        status=apply_xml(element,rule['edits'])
        pending[path]=ET.tostring(element,encoding='unicode',xml_declaration=True)+'\n'
        statuses.append({'path':rule['path'],**status})
    for dep in patch.get('dependencies',[]):
        if dep['class'] not in index or not member_available(dep['class'],dep['member'],index,pending):
            raise Conflict('Patch dependency missing: '+dep['class']+'->'+dep['member'])
    for path,text in pending.items():
        path.write_text(text,encoding='utf-8')
    result={'status':'PASS','format':FORMAT,'whole_file_replacements':0,
            'modified_files':sorted(p.relative_to(root).as_posix() for p in pending),
            'operations':statuses,'runtime_tested':False}
    if report:write_json(report,result)
    return result

def logical_method(text: str, symbols):
    raw=tokens(text,symbols)
    ls=[]; meta=[]; i=0
    while i<len(raw):
        x=raw[i]
        if x.startswith('.annotation '):
            block=[x]; i+=1
            while i<len(raw):
                block.append(raw[i])
                if raw[i]=='.end annotation':
                    break
                i+=1
            meta.append('\\n'.join(block))
        elif x.startswith(('.catch ', '.catchall ')):
            meta.append(x)
        else:
            ls.append(x)
        i+=1
    _,labels=shape_data(ls)
    mapping={k:':position_'+str(v) for k,v in labels.items()}
    result=[]; in_payload=False
    for x in ls:
        if x.startswith(('.packed-switch ', '.sparse-switch', '.array-data ')):in_payload=True
        if x.startswith(('.end packed-switch', '.end sparse-switch', '.end array-data')):in_payload=False
        if not x.startswith(':') or in_payload:
            x=label_replace(x,mapping)
            x=re.sub(r'^const-string/jumbo ', 'const-string ', x)
            x=re.sub(r'^goto(?:/16|/32) ', 'goto ', x)
            x=re.sub(r'^move(-wide|-object)?(?:/from16|/16) ', r'move\\1 ', x)
            result.append(x)
    normalized_meta=sorted(label_replace(x,mapping) for x in meta)
    result.extend('@meta '+x for x in normalized_meta)
    return result

def logical_class(text: str, symbols):
    methods,rest=split_methods(text)
    header=tokens(rest,symbols)
    if '.end field' not in header:
        fields=sorted(x for x in header if x.startswith('.field '))
        header=[x for x in header if not x.startswith('.field ')]
    else:
        fields=[]
    return {'header':header,'fields':fields,'methods':{k:logical_method(m[0],symbols) for k,m in methods.items()}}

def logical_xml(element):
    text=node_text(element)
    if len(element):text=text.strip()
    children=[logical_xml(x) for x in element]
    if element.tag=='attr':children.sort(key=repr)
    tail=element.tail or ''
    if not tail.strip():tail=''
    return (element.tag, sorted(element.attrib.items()),text,children,tail)

def verify(old: Path, target: Path, report: Path | None=None):
    sa=resource_map(old);sb=resource_map(target);ia=class_index(old);ib=class_index(target);bad=[];details={}
    if ia.keys()!=ib.keys():bad.append('class set differs')
    for name in ia.keys()&ib.keys():
        a=ia[name].read_text();b=ib[name].read_text()
        if a!=b:
            la=logical_class(a,sa);lb=logical_class(b,sb)
            if la!=lb:
                bad.append(name)
                if len(details)<4:
                    left=json.dumps(la,ensure_ascii=False,indent=2,sort_keys=True).splitlines()
                    right=json.dumps(lb,ensure_ascii=False,indent=2,sort_keys=True).splitlines()
                    details[name]=list(difflib.unified_diff(left,right,fromfile='candidate',tofile='roundtrip',n=3))[:120]
    aa={p.relative_to(old).as_posix() for p in old.rglob('*.xml') if p.relative_to(old).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    bb={p.relative_to(target).as_posix() for p in target.rglob('*.xml') if p.relative_to(target).as_posix().startswith(('res/', 'AndroidManifest.xml'))}
    if aa!=bb:bad.append('XML resource set differs')
    for path in aa&bb:
        if (old/path).read_bytes()!=(target/path).read_bytes():
            if logical_xml(ET.parse(old/path).getroot())!=logical_xml(ET.parse(target/path).getroot()):bad.append(path)
    result={'status':'FAIL' if bad else 'PASS','classes_compared':len(ia),'xml_files_compared':len(aa),'differences':sorted(bad),
            'details':details,
            'comparison':'decoded instructions, branch targets, class metadata and XML properties; ignores nops/formatting/debug info','runtime_tested':False}
    if report:write_json(report,result)
    if bad:raise Conflict('Logical verification failed: '+str(bad[:20]))
    print(json.dumps(result,indent=2));return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);subs=parser.add_subparsers(dest='cmd',required=True)
    ex=subs.add_parser('extract');ex.add_argument('old',type=Path);ex.add_argument('new',type=Path);ex.add_argument('output',type=Path)
    ap=subs.add_parser('apply');ap.add_argument('root',type=Path);ap.add_argument('patch',type=Path);ap.add_argument('--report',type=Path)
    ve=subs.add_parser('verify');ve.add_argument('expected',type=Path);ve.add_argument('actual',type=Path);ve.add_argument('--report',type=Path)
    args=parser.parse_args()
    try:
        if args.cmd=='extract':extract(args.old,args.new,args.output)
        elif args.cmd=='apply':apply(args.root,json.loads(args.patch.read_text()),args.report)
        else:verify(args.expected,args.actual,args.report)
    except (Conflict,ValueError,ET.ParseError) as exc:
        if hasattr(args,'report') and args.report and args.cmd!='verify':write_json(args.report,{'status':'CONFLICT','error':str(exc),'whole_file_replacements':0})
        print('ERROR: '+str(exc),file=sys.stderr);return 1
    return 0
if __name__=='__main__':sys.exit(main())
