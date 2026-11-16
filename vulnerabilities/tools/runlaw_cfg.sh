#!/usr/bin/env bash
# The model review of the 40 strongest lapsed time limits in law texts, with "law texts" read from config.json's not_law
# (every prefix, the Constitutional Court decisions filed in vendim/ among them) rather than a regular expression.
# Reviews already made are kept (triage.py skips ids it has).   bash runlaw_cfg.sh
set -e
cd "$(dirname "$0")/gl/vulnerabilities/scripts"
source ./llm_env.sh
export PYTHONIOENCODING=utf-8
P="C:/Python314/python.exe -X utf8"
mkdir -p findings/runlaw && $P -c "
import json, pyarrow as pa, pyarrow.parquet as pq
t = pq.read_table('findings/run/ranked_lapsed_limit.parquet')
cfg = json.load(open('../../../config.json', encoding='utf-8'))
nl = tuple(cfg['not_law']); files = tuple(cfg.get('not_law_files', []))
keep = [not (p.startswith(nl) or p.rsplit('/', 1)[-1] in files) for p in t.column('path').to_pylist()]
pq.write_table(t.filter(pa.array(keep)), 'findings/runlaw/ranked_lapsed_limit.parquet')
print(sum(keep), 'of', len(keep), 'lapsed flags in law texts')"
$P triage/triage.py runlaw --per 40 --workers 12 --dets lapsed_limit
echo RUNLAW DONE
