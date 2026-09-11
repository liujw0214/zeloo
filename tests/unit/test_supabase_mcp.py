"""Tests for optional_mcps.supabase MCP server."""

from optional_mcps.supabase import TOOLS, _fmt_row, _get_headers


class TestSupabaseFormatting:
    def test_fmt_row_basic(self):
        row = {"id": 1, "name": "Alice", "email": "a@b.com"}
        result = _fmt_row(row)
        assert "id=1" in result
        assert "name='Alice'" in result

    def test_fmt_row_truncates_long(self):
        row = {"data": "x" * 200}
        result = _fmt_row(row)
        assert len(result) < 150

    def test_fmt_row_max_8_items(self):
        row = {f"col_{i}": i for i in range(20)}
        result = _fmt_row(row)
        assert result.count("=") <= 8

    def test_get_headers_uses_key(self):
        import os
        original = os.environ.get("SUPABASE_KEY")
        try:
            os.environ["SUPABASE_KEY"] = "test-key"
            headers = _get_headers()
            assert headers["apikey"] == "test-key"
            assert "Bearer test-key" in headers["Authorization"]
        finally:
            if original is None:
                os.environ.pop("SUPABASE_KEY", None)
            else:
                os.environ["SUPABASE_KEY"] = original


class TestSupabaseToolsList:
    def test_tools_defined(self):
        assert len(TOOLS) == 10
        names = [t.name for t in TOOLS]
        # 原有 4 个
        assert "supabase_list_tables" in names
        assert "supabase_select" in names
        assert "supabase_insert" in names
        assert "supabase_auth_signup" in names
        # 新增 6 个（docs/31 §九承诺）
        assert "supabase_auth_signin" in names
        assert "supabase_update" in names
        assert "supabase_delete" in names
        assert "supabase_storage_upload" in names
        assert "supabase_storage_download" in names
        assert "supabase_rpc" in names

    def test_all_have_handlers(self):
        for tool in TOOLS:
            assert callable(tool.handler), f"{tool.name} has no handler"