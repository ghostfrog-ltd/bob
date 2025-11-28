# script_to_process_files.py
import os

# Comment marker for each file type could be enhanced; now all files receive a python style comment.
# Could be adjusted to handle other file types in future.

COMMENT_STYLES = {
    '.py': '#',
    '.js': '//',
    '.ts': '//',
    '.java': '//',
    '.go': '//',
    '.c': '//',
    '.cpp': '//',
    '.h': '//',
    '.json': '//',  # Not a comment-valid file but will prepend anyway
    '.sh': '#',
    '.md': '<!--',
    '.txt': '#',
}


def comment_marker_for_file(filename):
    _, ext = os.path.splitext(filename)
    return COMMENT_STYLES.get(ext, '#')


def list_files_to_edit(root_dir):
    files_to_edit = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if '.git' in dirnames:
            dirnames.remove('.git')  # ignore the .git directory
        for file in filenames:
            files_to_edit.append(os.path.join(dirpath, file))
    return files_to_edit


def prepend_comment_to_file(filepath, root_dir):
    rel_path = os.path.relpath(filepath, root_dir)
    comment_marker = comment_marker_for_file(filepath)
    if comment_marker == '<!--':
        comment_line = f'<!-- {rel_path} -->'
    else:
        comment_line = f'{comment_marker} {rel_path}'
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return False

    # Check if already prepended
    if content.startswith(comment_line):
        return True

    new_content = comment_line + '\n' + content

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
    except Exception:
        return False

    return True


def main():
    root_dir = '.'
    files = list_files_to_edit(root_dir)

    for file_path in files:
        prepend_comment_to_file(file_path, root_dir)


if __name__ == '__main__':
    main()
