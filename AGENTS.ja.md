# Zeloo Agent — ワークスペース規約

本ファイルは、このプロジェクトにおける Agent の動作規約を定義し、system prompt の context 層に自動的に注入されます。

## プロジェクト概要

Zeloo は、自己ホスト型・自己進化する常駐型 AI Agent ランタイムフレームワークです。

## 開発規約

- PEP 8 コードスタイルを遵守
- 型注釈は完全であること
- すべての公開関数に docstring が必要
- 依存関係はすべて正確なバージョン固定（`==X.Y.Z`）

## アーキテクチャ規約

- System Prompt は3層構成：stable / context / volatile
- ツールは `@tool` デコレータで自動登録
- メモリとスキルはランタイム可变、キャッシュ層は安定維持
- ワークスペース（`workspace/`）とアーカイブ（`archive/`）は分離管理

## ワークスペース規約

### ワークスペース

各ワークスペースは独立した自己完結型プロジェクト環境です：

```
~/.Zeloo/workspace/
├── workspace.json       # ワークスペースインデックス
├── default/           # デフォルトワークスペース
│   ├── profile/       # Zeloo設定（config.yaml、.env）
│   ├── memory/        # 永続メモリ（MEMORY.md、USER.md）
│   ├── skills/        # ワークスペースローカルスキル
│   ├── SOUL.md        # 任意ローカルアイデンティティ
│   └── metadata.json # ワークスペースメタデータ
├── project-alpha/      # プロジェクトA
└── project-beta/      # プロジェクトB
```

### アーカイブ

ワークスペースの圧縮スナップショットで、いつでも復元可能：

```
~/.Zeloo/archive/
├── archive.json              # アーカイブインデックス
├── default/                  # ワークスペース別整理
│   ├── snap_20260907.tar.zst
│   └── snap_milestone.tar.zst
└── project-alpha/
    └── snap_pre_delete.tar.zst
```

### 操作規範

1. **ワークスペース作成**: `workspace_create` — 既存ワークスペースから複製または新規作成
2. **ワークスペース切替**: `workspace_switch` — last_active タイムスタンプ更新
3. **ワークスペーススナップショット**: `workspace_archive` — .tar.zst 圧縮スナップショット作成
4. **ワークスペース復元**: `workspace_restore` — スナップショットから新規ワークスペースとして復元
5. **ワークスペース削除** — 削除前に自動アーカイブ（明示的に無効化した場合を除く）

### タグと検索

- ワークスペースはタグをサポート（`workspace_add_tag`）
- タグでワークスペースリストをフィルタ可能
- `last_active` タイムスタンプでソート

### 移行ルール

- `memory/` ファイルをプロジェクト間で共有しない — 各ワークスペースは独立
- `profile/` は機密情報を含む — アーカイブ前に `.env` に平文キーを含めないよう確認
- 復元時は常に新規ワークスペースを作成 — 同名ワークスペースを上書きしない
