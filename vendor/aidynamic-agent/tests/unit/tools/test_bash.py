import os
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, main

from aidynamic_agent.tools.builtins.bash import BashTool


class TestBashTool(IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = BashTool(timeout=5.0)

    async def test_simple_command(self):
        result = await self.tool.execute(command="echo hello")
        self.assertTrue(result.success)
        self.assertEqual(result.content, "hello")

    async def test_command_with_output(self):
        result = await self.tool.execute(command="pwd")
        self.assertTrue(result.success)
        self.assertTrue(len(result.content) > 0)

    async def test_failed_command(self):
        result = await self.tool.execute(command="ls /nonexistent_path_xyz_12345")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    async def test_empty_command(self):
        result = await self.tool.execute(command="")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Empty command")

    async def test_whitespace_only_command(self):
        result = await self.tool.execute(command="   ")
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Empty command")

    async def test_dangerous_rm_rf_root(self):
        result = await self.tool.execute(command="rm -rf /")
        self.assertFalse(result.success)
        self.assertIn("dangerous", result.error.lower())

    async def test_dangerous_mkfs(self):
        result = await self.tool.execute(command="mkfs.ext4 /dev/sda1")
        self.assertFalse(result.success)
        self.assertIn("dangerous", result.error.lower())

    async def test_pipe_command(self):
        result = await self.tool.execute(command="echo test | grep test")
        self.assertTrue(result.success)
        self.assertIn("test", result.content)

    async def test_multiline_command(self):
        result = await self.tool.execute(command="echo line1 && echo line2")
        self.assertTrue(result.success)
        self.assertIn("line1", result.content)
        self.assertIn("line2", result.content)

    async def test_returncode_metadata(self):
        result = await self.tool.execute(command="echo ok")
        self.assertTrue(result.success)
        self.assertIn("returncode", result.metadata)
        self.assertEqual(result.metadata["returncode"], 0)

    async def test_dangerous_sudo_reboot(self):
        result = await self.tool.execute(command="sudo reboot")
        self.assertFalse(result.success)
        self.assertIn("dangerous", result.error.lower())

    async def test_dangerous_dd(self):
        result = await self.tool.execute(command="dd if=/dev/zero of=/dev/sda")
        self.assertFalse(result.success)
        self.assertIn("dangerous", result.error.lower())

    async def test_safe_rm_not_root(self):
        # rm -rf on a non-root path should NOT be rejected
        with tempfile.TemporaryDirectory() as tmp:
            test_dir = os.path.join(tmp, "testdir")
            os.makedirs(test_dir)
            Path(os.path.join(test_dir, "file.txt")).write_text("test")
            result = await self.tool.execute(command=f"rm -rf {test_dir}")
            self.assertTrue(result.success)
            self.assertFalse(os.path.exists(test_dir))


class TestBashToolTimeout(IsolatedAsyncioTestCase):
    async def test_timeout(self):
        tool = BashTool(timeout=0.1)
        result = await tool.execute(command="sleep 10")
        self.assertFalse(result.success)
        self.assertIn("timed out", result.error.lower())


if __name__ == "__main__":
    main()
