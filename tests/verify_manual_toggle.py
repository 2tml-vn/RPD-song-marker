import re
import sys

def verify_toggle_logic(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Verify initial isLocked is true
    if not re.search(r'let\s+isLocked\s*=\s*true', content):
        print("FAILED: isLocked should be initialized to true.")
        return False

    # Verify lockBtn click handler exists and has correct logic
    # It should toggle isLocked and update opacity
    toggle_pattern = r'lockBtn\.onclick\s*=\s*\(e\)\s*=>\s*\{[^}]*isLocked\s*=\s*!isLocked[^}]*container\.style\.opacity\s*=\s*isLocked\s*\?\s*["\']1["\']\s*:\s*["\']0\.2["\']'
    if not re.search(toggle_pattern, content):
        print("FAILED: lockBtn.onclick toggle logic is missing or incorrect.")
        return False

    print("PASSED: Manual toggle logic verified.")
    return True

if __name__ == "__main__":
    if not verify_toggle_logic('jrpd_marker.user.js'):
        sys.exit(1)
    sys.exit(0)

