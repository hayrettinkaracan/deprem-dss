"""Oturumluk Supabase karşılığı. Yalnızca DEPREM_DEMO=1 ve testler kullanır."""

import copy
import fnmatch
import re
from uuid import uuid4


def _eq(left, right):
    if left == right:
        return True
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _like(value, pattern):
    translated = []
    for ch in str(pattern):
        if ch == "%":
            translated.append("*")
        elif ch == "_":
            translated.append("?")
        elif ch in "*?[]":
            translated.append(f"[{ch}]")
        else:
            translated.append(ch)
    return fnmatch.fnmatchcase("" if value is None else str(value), "".join(translated))


def _split_select(spec):
    parts = []
    buf = []
    depth = 0
    for ch in spec:
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.op = "select"
        self.payload = None
        self.columns = "*"
        self.filters = []

    def select(self, columns="*"):
        self.op = "select"
        self.columns = columns
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def upsert(self, payload):
        # Şemada enkaz_id üzerinde çakışma anahtarı yok; upsert yeni satır ekler.
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def like(self, column, pattern):
        self.filters.append(("like", column, pattern))
        return self

    def execute(self):
        return self.db.execute(self)


class MemorySupabase:
    """Supabase sorgu zincirinin bellek içi karşılığı. Üretim istemcisi değildir."""

    is_memory = True

    def __init__(self):
        self.scope_id = uuid4().hex
        self.tables = {
            "enkazlar": [],
            "ekipler": [],
            "atamalar": [],
            "yardimci_kaynaklar": [],
        }
        self._seq = {name: 1 for name in self.tables}
        self.select_count = 0
        self.insert_calls = 0
        self._seed()

    def table(self, name):
        if name not in self.tables:
            self.tables[name] = []
            self._seq[name] = 1
        return _Query(self, name)

    def _seed(self):
        seed = {
            "enkazlar": [
                {
                    "id": 1,
                    "isim": "Avcılar-Merkez",
                    "enlem": 40.9792,
                    "boylam": 28.7214,
                    "talep": 820.4,
                    "makine_gerekli": 1,
                    "durum": "aktif",
                },
                {
                    "id": 2,
                    "isim": "Avcılar-Ambarlı",
                    "enlem": 40.9681,
                    "boylam": 28.7035,
                    "talep": 640,
                    "makine_gerekli": 0,
                    "durum": "aktif",
                },
                {
                    "id": 3,
                    "isim": "Kadıköy-Moda",
                    "enlem": 40.9830,
                    "boylam": 29.0252,
                    "talep": 0,
                    "makine_gerekli": 0,
                    "durum": "tamam",
                },
                {
                    "id": 4,
                    "isim": "Avcılar-Merkez",
                    "enlem": 40.9855,
                    "boylam": 28.7350,
                    "talep": 510.2,
                    "makine_gerekli": 1,
                    "durum": "aktif",
                },
            ],
            "ekipler": [
                {
                    "id": 1,
                    "isim": "AK-1",
                    "tip": "Arama-Kurtarma",
                    "kapasite": 120,
                    "durum": "meşgul",
                    "erisim_kodu": "ekip-1",
                },
                {
                    "id": 2,
                    "isim": "AK-1",
                    "tip": "Arama-Kurtarma",
                    "kapasite": 80,
                    "durum": "musait",
                    "erisim_kodu": "ekip-2",
                },
                {
                    "id": 3,
                    "isim": "AK-3",
                    "tip": "Arama-Kurtarma",
                    "kapasite": 100,
                    "durum": "musait",
                    "erisim_kodu": "ekip-3",
                },
            ],
            "atamalar": [
                {
                    "id": 1,
                    "ekip_id": 1,
                    "enkaz_id": 1,
                    "baslangic": "2026-11-23T06:30:00",
                    "bitis": None,
                    "durum": "devam",
                },
                {
                    "id": 2,
                    "ekip_id": 3,
                    "enkaz_id": 3,
                    "baslangic": "2026-11-22T18:00:00",
                    "bitis": "2026-11-22T22:15:00",
                    "durum": "bitti",
                },
            ],
            "yardimci_kaynaklar": [
                {"id": 1, "enkaz_id": 2, "umke_sayisi": 4, "makine_sayisi": 1},
                {"id": 2, "enkaz_id": 1, "umke_sayisi": 2, "makine_sayisi": 1},
            ],
        }
        for name, rows in seed.items():
            self.tables[name] = [dict(row) for row in rows]
            self._seq[name] = max(int(row["id"]) for row in rows) + 1

    def _match(self, row, filters):
        for op, column, expected in filters:
            if op == "eq" and not _eq(row.get(column), expected):
                return False
            if op == "like" and not _like(row.get(column), expected):
                return False
        return True

    def _embed(self, row, relation, columns):
        foreign = {"ekipler": "ekip_id", "enkazlar": "enkaz_id"}.get(relation)
        if foreign is None or relation not in self.tables:
            return None
        match = next(
            (item for item in self.tables[relation] if _eq(item.get("id"), row.get(foreign))),
            None,
        )
        if match is None:
            return None
        return {column: match.get(column) for column in columns}

    def _project(self, row, spec):
        if spec.strip() == "*":
            return dict(row)
        include_all = False
        projected = {}
        for part in _split_select(spec):
            if part == "*":
                include_all = True
                continue
            match = re.fullmatch(r"(\w+)\(([^)]*)\)", part)
            if match:
                relation = match.group(1)
                columns = [item.strip() for item in match.group(2).split(",") if item.strip()]
                projected[relation] = self._embed(row, relation, columns)
            else:
                projected[part] = row.get(part)
        if include_all:
            merged = dict(row)
            merged.update(projected)
            return merged
        return projected

    def execute(self, query):
        table = self.tables[query.table]
        if query.op == "select":
            self.select_count += 1
            rows = [self._project(row, query.columns) for row in table if self._match(row, query.filters)]
            return _Result(copy.deepcopy(rows))
        if query.op == "insert":
            self.insert_calls += 1
            payloads = query.payload if isinstance(query.payload, list) else [query.payload]
            inserted = []
            for item in payloads:
                row = dict(item)
                if row.get("id") is None:
                    row["id"] = self._seq[query.table]
                    self._seq[query.table] += 1
                else:
                    self._seq[query.table] = max(self._seq[query.table], int(row["id"]) + 1)
                table.append(row)
                inserted.append(dict(row))
            return _Result(inserted)
        if query.op == "update":
            updated = []
            for row in table:
                if self._match(row, query.filters):
                    row.update(query.payload)
                    updated.append(dict(row))
            return _Result(updated)
        if query.op == "delete":
            kept = []
            deleted = []
            for row in table:
                if self._match(row, query.filters):
                    deleted.append(dict(row))
                else:
                    kept.append(row)
            self.tables[query.table] = kept
            return _Result(deleted)
        raise ValueError(query.op)
