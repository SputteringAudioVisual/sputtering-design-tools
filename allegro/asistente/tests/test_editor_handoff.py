import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor_handoff import editor_command,launch_editor


class EditorHandoffTests(unittest.TestCase):
    def test_builds_command_with_the_exact_board_and_fabrication_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);python=root/'pythonw.exe';entry=root/'sputtering_design_tools.py'
            board=root/'board.brd';archive=root/'F001.zip'
            for path in (python,entry,board,archive):path.write_bytes(b'x')
            details=dict(target=str(python),arguments='"'+str(entry)+'"',workingDirectory=str(root))
            command=editor_command(details,board,archive)
            self.assertEqual(command,[str(python),str(entry),'--board',str(board),'--fabrication',str(archive)])

    def test_launch_uses_registered_shortcut_and_does_not_rewrite_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);python=root/'pythonw.exe';entry=root/'app.py'
            board=root/'board.brd';archive=root/'F002.zip'
            for path in (python,entry,board,archive):path.write_bytes(b'x')
            details=dict(target=str(python),arguments='"'+str(entry)+'"',workingDirectory=str(root))
            process=Mock()
            result=launch_editor(board,archive,details=details,popen=process)
            process.assert_called_once()
            args,kwargs=process.call_args
            self.assertEqual(args[0][-4:],['--board',str(board),'--fabrication',str(archive)])
            self.assertEqual(kwargs['cwd'],str(root))
            self.assertIs(result,process.return_value)

    def test_missing_exact_zip_is_reported_without_launching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);python=root/'pythonw.exe';entry=root/'app.py';board=root/'board.brd'
            for path in (python,entry,board):path.write_bytes(b'x')
            details=dict(target=str(python),arguments='"'+str(entry)+'"',workingDirectory=str(root))
            process=Mock()
            with self.assertRaisesRegex(FileNotFoundError,'ZIP'):
                launch_editor(board,root/'missing.zip',details=details,popen=process)
            process.assert_not_called()


if __name__=='__main__':unittest.main()
