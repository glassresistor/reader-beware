import os
import shutil
import pytest
from beware.build_html import NarrativeWorldBuilder

def test_single_file_mode(tmp_path):
    yaml_file = tmp_path / "narrative.yaml"
    yaml_file.write_text("""
entrypoint:
  body: |
    Hello!
    [go]({{ 'next'|explore }})
next:
  body: Goodbye!
""")
    output = tmp_path / "output"
    builder = NarrativeWorldBuilder(str(yaml_file), str(output))
    assert "entrypoint" in builder.narratives
    assert "next" in builder.narratives
    assert "Hello!" in builder.narratives["entrypoint"]["body"]

def test_folder_mode_markdown(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "entrypoint.md").write_text("Start\n[go]({{ 'next'|explore }})")
    (folder / "next.md").write_text("End")
    
    output = tmp_path / "output"
    builder = NarrativeWorldBuilder(str(folder), str(output))
    assert "entrypoint" in builder.narratives
    assert "next" in builder.narratives
    assert builder.narratives["entrypoint"]["body"] == "Start\n[go]({{ 'next'|explore }})"

def test_folder_mode_filename_as_section(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    # Use __ to test the extraction logic
    (folder / "entrypoint__start.md").write_text("Start")
    (folder / "next__end.md").write_text("End")
    
    output = tmp_path / "output"
    builder = NarrativeWorldBuilder(str(folder), str(output))
    builder.folder_mode_filename_as_section = False
    assert "start" in builder.narratives
    assert "end" in builder.narratives

def test_folder_mode_yaml(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    # Ensure the first file triggers is_yaml_mode
    (folder / "01_entrypoint.yaml").write_text("""
entrypoint:
  body: "Start"
""")
    (folder / "02_next.yaml").write_text("""
next:
  body: "End"
""")
    
    output = tmp_path / "output"
    builder = NarrativeWorldBuilder(str(folder), str(output))
    assert "entrypoint" in builder.narratives
    assert "next" in builder.narratives
    assert builder.narratives["entrypoint"]["body"] == "Start"
    assert builder.narratives["next"]["body"] == "End"

def test_folder_mode_mixed_error(tmp_path):
    # Test that it doesn't crash if we mix, but follows the first file's mode
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "01_entrypoint.md").write_text("Start")
    (folder / "02_next.yaml").write_text("next: {body: 'End'}")
    
    output = tmp_path / "output"
    builder = NarrativeWorldBuilder(str(folder), str(output))
    # Should be markdown mode because 01 is .md and doesn't start with ---
    assert "01_entrypoint" in builder.narratives
    assert "02_next" in builder.narratives
