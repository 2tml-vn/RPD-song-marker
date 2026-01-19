import re
import sys

def verify_js_logic(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check for any auto-dimming patterns
    # Look for setTimeout/setInterval that target container.style.opacity
    timers = re.findall(r'(setTimeout|setInterval)\s*\(\s*\(\s*\)\s*=>\s*\{[^}]*container\.style\.opacity[^}]*\}', content)
    if timers:
        print(f"FAILED: Found potential auto-dimming timers targeting container: {timers}")
        return False

    # Check initial opacity setting
    # We now expect 1.0 or 1
    initial_opacity_dimmed = re.search(r'container\.style\.opacity\s*=\s*["\']0\.2["\']', content)
    if initial_opacity_dimmed:
        print(f"FAILED: Found initial dimmed opacity setting (0.2): {initial_opacity_dimmed.group(0)}")
        return False

    print("PASSED: No auto-dimming logic or initial dimming detected.")
    return True

if __name__ == "__main__":
    if not verify_js_logic('jrpd_marker.user.js'):
        sys.exit(1)
    sys.exit(0)

