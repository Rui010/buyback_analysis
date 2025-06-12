## カラムの追加

- `announcements` テーブルにTEXT型の `status` カラムを追加

## テーブルの追加

```
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    url TEXT,
    company_name TEXT NOT NULL,
    disclosure_date TEXT NOT NULL,
    original_announcement_date TEXT NOT NULL,
    document_title TEXT NOT NULL,
    correction_reason TEXT,
    corrections TEXT NOT NULL
);
```