from pathlib import Path

import pytest

from memory_center.service.integrations import install_skills


def test_install_preserves_custom_skill_and_bundles_new_protocol(tmp_path):
    destination = tmp_path / '.codex/skills/wiki/SKILL.md'
    destination.parent.mkdir(parents=True)
    destination.write_text('customized')
    with pytest.raises(FileExistsError):
        install_skills(tmp_path, ['codex'])
    install_skills(tmp_path, ['codex'], force=True)
    assert destination.with_suffix('.md.before-v5').read_text() == 'customized'
    assert 'workspace_id' in destination.read_text()
    assert '--workspace' not in destination.read_text()
    assert Path(destination.parent / 'agents/openai.yaml').exists()
