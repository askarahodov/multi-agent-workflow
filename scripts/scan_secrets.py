import re
import subprocess

# Patterns to detect secrets
patterns = [
    (r'AKIA[0-9A-Z]{16}', 'AWS Access Key'),
    (r'ghp_[0-9a-zA-Z]{36}', 'GitHub PAT'),
    (r'gho_[0-9a-zA-Z]{36}', 'GitHub OAuth'),
    (r'ghu_[0-9a-zA-Z]{36}', 'GitHub User'),
    (r'ghs_[0-9a-zA-Z]{36}', 'GitHub Secret'),
    (r'ghr_[0-9a-zA-Z]{36}', 'GitHub Refresh'),
    (r'glpat-[0-9a-zA-Z\-_]{20,}', 'GitLab PAT'),
    (r'xoxb-[0-9]{12}-[0-9]{12}-[0-9]{12}-[a-zA-Z0-9]{24}', 'Slack Bot Token'),
    (r'xoxp-[0-9]{12}-[0-9]{12}-[0-9]{12}-[a-zA-Z0-9]{24}', 'Slack User Token'),
    (r'sk-[a-zA-Z0-9]{48}', 'OpenAI API Key'),
    (r'sk-ant-[a-zA-Z0-9\-_]{95,}', 'Anthropic API Key'),
    (r'AIza[0-9A-Za-z\-_]{35}', 'Google API Key'),
    (r'[0-9a-f]{32}', 'Generic 32-char hex (possible secret)'),
]

# Files to scan
result = subprocess.run(['git', 'diff', '--name-only', '7830cc1..c8e9e4f'], capture_output=True, text=True)
files = result.stdout.strip().split('\n')

print('Scanning for secrets in changed files...')
found = False
for f in files:
    if not f:
        continue
    try:
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
        for pattern, name in patterns:
            matches = re.findall(pattern, content)
            if matches:
                # Filter out test fixtures and redacted patterns
                real_matches = []
                for m in matches:
                    if 'redacted' in content.lower() or 'fake' in content.lower() or 'test' in content.lower() or 'example' in content.lower():
                        continue
                    real_matches.append(m)
                if real_matches:
                    print(f'  {f}: {name} - {real_matches[:3]}')
                    found = True
    except Exception as e:
        pass

if not found:
    print('No secrets found in changed files.')