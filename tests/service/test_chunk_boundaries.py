"""真实嵌入失败回归：空白块与超长压缩单行。"""
from memory_center.platform.jobs import split_text


def test_blank_chunks_not_sent_to_models():
    assert split_text('\n   \n\t', {'source_id': 'blank'}) == []
    chunks = split_text('first\n\n'+' '*1900+'\n\nlast', {'source_id': 'demo'})
    assert all(chunk['content'].strip() for chunk in chunks)
    assert chunks[0]['metadata']['line'] == 1
    assert chunks[-1]['metadata']['end_line'] == 5


def test_minified_line_is_complete_and_locatable():
    long_line = 'const payload="'+('x' * 941000)+'";'
    chunks = split_text(long_line, {'source_id': 'minified', 'path': 'fixture.js'})
    assert ''.join(chunk['content'] for chunk in chunks) == long_line
    assert max(len(chunk['content']) for chunk in chunks) <= 1800
    assert len({chunk['id'] for chunk in chunks}) == len(chunks)
    for chunk in chunks:
        source = chunk['metadata']
        assert source['line'] == source['end_line'] == 1
        assert long_line[source['column'] - 1:source['end_column']] == chunk['content']


def test_fences_and_long_lines_preserve_source_lines():
    lines = ['intro', '```js', 'x'*8000, 'code', '```', 'last']
    chunks = split_text('\n'.join(lines), {'source_id': 'fixture'})
    assert all(len(chunk['content']) <= 6000 for chunk in chunks)
    for chunk in chunks:
        source = chunk['metadata']
        if 'column' in source:
            assert lines[source['line']-1][source['column']-1:source['end_column']] == chunk['content']
        else:
            assert '\n'.join(lines[source['line']-1:source['end_line']]) == chunk['content']
