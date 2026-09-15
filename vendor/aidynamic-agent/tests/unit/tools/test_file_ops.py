import os
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, main

from aidynamic_agent.tools.builtins.file_ops import FileOpsTool


class TestFileOpsRead(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = FileOpsTool()
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_read_file(self):
        path = os.path.join(self.tmpdir.name, "test.txt")
        Path(path).write_text("line1\nline2\nline3\n")
        result = await self.tool.execute(operation="read", path=path)
        self.assertTrue(result.success)
        self.assertIn("1|line1", result.content)
        self.assertIn("2|line2", result.content)
        self.assertIn("3|line3", result.content)

    async def test_read_with_offset(self):
        path = os.path.join(self.tmpdir.name, "test.txt")
        Path(path).write_text("line1\nline2\nline3\n")
        result = await self.tool.execute(operation="read", path=path, offset=2)
        self.assertTrue(result.success)
        self.assertIn("2|line2", result.content)
        self.assertIn("3|line3", result.content)
        self.assertNotIn("1|line1", result.content)

    async def test_read_with_limit(self):
        path = os.path.join(self.tmpdir.name, "test.txt")
        Path(path).write_text("line1\nline2\nline3\nline4\nline5\n")
        result = await self.tool.execute(operation="read", path=path, limit=2)
        self.assertTrue(result.success)
        self.assertIn("1|line1", result.content)
        self.assertIn("2|line2", result.content)
        self.assertNotIn("3|line3", result.content)
        self.assertIn("has_more", result.metadata)

    async def test_read_nonexistent(self):
        result = await self.tool.execute(operation="read", path="/nonexistent_xyz.txt")
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    async def test_read_directory(self):
        result = await self.tool.execute(operation="read", path=self.tmpdir.name)
        self.assertFalse(result.success)
        self.assertIn("not a file", result.error.lower())


class TestFileOpsWrite(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = FileOpsTool()
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_write_file(self):
        path = os.path.join(self.tmpdir.name, "output.txt")
        result = await self.tool.execute(operation="write", path=path, content="hello world")
        self.assertTrue(result.success)
        self.assertIn("written", result.content.lower())
        self.assertEqual(Path(path).read_text(), "hello world")

    async def test_write_creates_parent_dirs(self):
        path = os.path.join(self.tmpdir.name, "a", "b", "c", "file.txt")
        result = await self.tool.execute(operation="write", path=path, content="nested")
        self.assertTrue(result.success)
        self.assertEqual(Path(path).read_text(), "nested")

    async def test_write_overwrites(self):
        path = os.path.join(self.tmpdir.name, "output.txt")
        Path(path).write_text("old content")
        result = await self.tool.execute(operation="write", path=path, content="new content")
        self.assertTrue(result.success)
        self.assertEqual(Path(path).read_text(), "new content")

    async def test_write_empty_content(self):
        path = os.path.join(self.tmpdir.name, "empty.txt")
        result = await self.tool.execute(operation="write", path=path, content="")
        self.assertTrue(result.success)
        self.assertEqual(Path(path).read_text(), "")


class TestFileOpsPatch(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = FileOpsTool()
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_patch_file(self):
        path = os.path.join(self.tmpdir.name, "patch_me.txt")
        Path(path).write_text("hello world")
        result = await self.tool.execute(
            operation="patch", path=path, old_string="world", new_string="there"
        )
        self.assertTrue(result.success)
        self.assertEqual(Path(path).read_text(), "hello there")

    async def test_patch_not_found(self):
        path = os.path.join(self.tmpdir.name, "patch_me.txt")
        Path(path).write_text("hello world")
        result = await self.tool.execute(
            operation="patch", path=path, old_string="nonexistent", new_string="foo"
        )
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    async def test_patch_nonexistent_file(self):
        result = await self.tool.execute(
            operation="patch", path="/nonexistent.txt", old_string="a", new_string="b"
        )
        self.assertFalse(result.success)

    async def test_patch_multiple_occurrences_single(self):
        path = os.path.join(self.tmpdir.name, "multi.txt")
        Path(path).write_text("foo bar foo bar")
        result = await self.tool.execute(
            operation="patch", path=path, old_string="foo", new_string="baz"
        )
        self.assertTrue(result.success)
        self.assertEqual(Path(path).read_text(), "baz bar foo bar")

    async def test_patch_replace_all(self):
        path = os.path.join(self.tmpdir.name, "multi.txt")
        Path(path).write_text("foo bar foo bar")
        result = await self.tool.execute(
            operation="patch",
            path=path,
            old_string="foo",
            new_string="baz",
            replace_all=True,
        )
        self.assertTrue(result.success)
        self.assertEqual(Path(path).read_text(), "baz bar baz bar")


class TestFileOpsSearch(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = FileOpsTool()
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_search_in_file(self):
        path = os.path.join(self.tmpdir.name, "search.txt")
        Path(path).write_text("hello world\nfoo bar\nhello again\n")
        result = await self.tool.execute(operation="search", path=path, pattern="hello")
        self.assertTrue(result.success)
        self.assertIn("hello world", result.content)
        self.assertIn("hello again", result.content)

    async def test_search_in_directory(self):
        path = os.path.join(self.tmpdir.name, "dir1")
        os.makedirs(path)
        Path(os.path.join(path, "a.txt")).write_text("apple banana")
        Path(os.path.join(path, "b.txt")).write_text("cherry date")

        result = await self.tool.execute(operation="search", path=path, pattern="apple")
        self.assertTrue(result.success)
        self.assertIn("apple", result.content)

    async def test_search_no_matches(self):
        path = os.path.join(self.tmpdir.name, "search.txt")
        Path(path).write_text("no match here")
        result = await self.tool.execute(operation="search", path=path, pattern="xyz_not_found")
        self.assertTrue(result.success)
        self.assertIn("no match", result.content.lower())

    async def test_search_nonexistent_path(self):
        result = await self.tool.execute(
            operation="search", path="/nonexistent_dir", pattern="test"
        )
        self.assertFalse(result.success)

    async def test_search_invalid_regex(self):
        path = os.path.join(self.tmpdir.name, "search.txt")
        Path(path).write_text("test content")
        result = await self.tool.execute(operation="search", path=path, pattern="[invalid")
        self.assertFalse(result.success)
        self.assertIn("invalid", result.error.lower())

    async def test_search_match_count(self):
        path = os.path.join(self.tmpdir.name, "count.txt")
        Path(path).write_text("aaa\nbbb\naaa\naaa\n")
        result = await self.tool.execute(operation="search", path=path, pattern="aaa")
        self.assertTrue(result.success)
        self.assertEqual(result.metadata.get("match_count"), 3)


class TestFileOpsUnknownOperation(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = FileOpsTool()

    async def test_unknown_operation(self):
        result = await self.tool.execute(operation="delete", path="/tmp/test.txt")
        self.assertFalse(result.success)
        self.assertIn("unknown", result.error.lower())


if __name__ == "__main__":
    main()
