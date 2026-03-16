# Auto-Fix Test Script Guide

## Overview

The new `test_portfolio_integrity_autofix.py` script automatically:
1. Tests portfolio manager calculations
2. Detects issues
3. **Auto-fixes common problems**
4. Creates backups of modified files
5. Reports all changes clearly

## Installation

The script is ready to use. No additional dependencies needed.

## Usage

### Default Mode (With Auto-Fix)
```bash
python test_portfolio_integrity_autofix.py
```

This will:
- Run all 4 tests
- Automatically fix any issues found
- Create backups of modified files
- Show detailed report of all fixes

### Test-Only Mode (No Auto-Fix)
```bash
python test_portfolio_integrity_autofix.py --no-fix
```

This will:
- Run all tests
- Report failures
- NOT modify any files
- Useful for just checking status

## What Gets Tested

### Test 1: Capital Consistency ✓
Verifies: `capital = free_cap + committed + unrealized`

**Example Output:**
```
Strategy: EMA5_Momentum
  Total Capital:    $1,438.57
  Free Capital:     $928.57
  Committed:        $300.00
  Realized P&L:     $0.00
  Unrealized P&L:   +$10.00

Consistency Check:
Total Capital = $1,438.57
Free + Committed + Unrealized = $1,438.57
✓ PASS: Capital values are consistent
```

### Test 2: Reallocate Method Signature ✓
Verifies: `reallocate(current_price)` accepts parameter

**Auto-Fix:** If test fails, changes:
```python
# Before
def reallocate(self):

# To
def reallocate(self, current_price: float = 0.0):
```

### Test 3: _allocate_capital Method Signature ✓
Verifies: `_allocate_capital(current_price)` accepts parameter

**Auto-Fix:** If test fails, changes:
```python
# Before
def _allocate_capital(self):

# To
def _allocate_capital(self, current_price: float = 0.0):
```

### Test 4: Dashboard Calculations ✓
Verifies: Dashboard code contains correct calculation patterns

**Checks for:**
- `true_total_cap` variable exists
- Formula: `true_total_cap = total_allocated + unrealized_pnl`
- Display: `"Total Cap": f"${true_total_cap:,.2f}"`

## Output Explained

### Color Coding
- 🟢 **GREEN**: Test passed or fix successful
- 🔴 **RED**: Test failed (needs attention)
- 🟡 **YELLOW**: Warning or backup notification
- 🔵 **BLUE**: Information/current test running

### Example Full Run

```
══════════════════════════════════════════════════════════════════════
PORTFOLIO MANAGER - TEST SUITE WITH AUTO-FIX
══════════════════════════════════════════════════════════════════════

══════════════════════════════════════════════════════════════════════
TEST 1: Capital Calculation Consistency
══════════════════════════════════════════════════════════════════════

Initial Balance:
  Total Balance: $10,000.00
  Free Capital:  $9,000.00
  Realized P&L:  $0.00
  Unrealized P&L: $0.00

Strategy: EMA5_Momentum
  Total Capital:    $1,428.57
  Free Capital:     $1,428.57
  Committed:        $0.00
  Realized P&L:     $0.00
  Unrealized P&L:   $0.00

  Consistency Check:
  Total Capital = $1,428.57
  Free + Committed + Unrealized = $1,428.57
  ✓ PASS: Capital values are consistent

══════════════════════════════════════════════════════════════════════
TEST 2: Reallocate Method Signature
══════════════════════════════════════════════════════════════════════

Testing reallocate() method...
  Calling: reallocate(current_price=30000.0)
  ✓ PASS: reallocate() accepts current_price parameter

══════════════════════════════════════════════════════════════════════
TEST 3: _allocate_capital Method Signature
══════════════════════════════════════════════════════════════════════

Test 3a: With current_price parameter...
  Calling: _allocate_capital(30000.0)
  ✓ PASS

Test 3b: With default parameter...
  Calling: _allocate_capital()
  ✓ PASS

══════════════════════════════════════════════════════════════════════
TEST 4: Dashboard Calculations
══════════════════════════════════════════════════════════════════════

Checking dashboard calculations...
  ✓ Found: true_total_cap calculation
  ✓ Found: correct formula
  ✓ Found: display of true_total_cap

✓ PASS: Dashboard calculations are correct

══════════════════════════════════════════════════════════════════════
TEST RESULTS SUMMARY
══════════════════════════════════════════════════════════════════════
✓ PASS: Capital Consistency
✓ PASS: Reallocate Signature
✓ PASS: Allocate Capital Signature
✓ PASS: Dashboard Calculations

Score: 4/4 tests passed

No fixes needed!

══════════════════════════════════════════════════════════════════════
✓ ALL TESTS PASSED - Portfolio is ready to use!
══════════════════════════════════════════════════════════════════════
```

### Example with Auto-Fix

If a signature was missing:

```
══════════════════════════════════════════════════════════════════════
TEST 2: Reallocate Method Signature
══════════════════════════════════════════════════════════════════════

Testing reallocate() method...
  Calling: reallocate(current_price=30000.0)
  ✗ FAIL: Signature error

Attempting auto-fix...

Fixing: Update reallocate() method signature
  File: portfolio_manager.py
  Backup created: portfolio_manager.py.backup_20260226_143022
  ✓ Fixed successfully

✓ Auto-fix successful! Please restart the bot.

══════════════════════════════════════════════════════════════════════
FIX SUMMARY
══════════════════════════════════════════════════════════════════════

1. Update reallocate() method signature
   File: portfolio_manager.py
   Backup: portfolio_manager.py.backup_20260226_143022

Total fixes applied: 1
Total backups created: 1

Backup locations:
  portfolio_manager.py.backup_20260226_143022

All fixes applied successfully!
```

## Backup System

All file modifications are protected:

### Auto-Backup Features
✓ **Automatic backup creation** before any file modification
✓ **Timestamped backups** (format: `filename.backup_YYYYMMDD_HHMMSS`)
✓ **Backup location report** at end of run
✓ **Easy restoration** if needed

### Restoring from Backup
If you need to undo changes:

```bash
# List backups
ls -lh *.backup_*

# Restore a specific backup
cp portfolio_manager.py.backup_20260226_143022 portfolio_manager.py
```

## Typical Workflows

### Workflow 1: Quick Health Check
```bash
# Just check status, don't modify anything
python test_portfolio_integrity_autofix.py --no-fix
```

### Workflow 2: Auto-Fix Everything
```bash
# Run tests and auto-fix all issues
python test_portfolio_integrity_autofix.py

# Restart bot if fixes were applied
python main.py
```

### Workflow 3: Review Before Fixing
```bash
# First check what would be fixed
python test_portfolio_integrity_autofix.py --no-fix

# Review backups if fixes were needed
ls -lh *.backup_*

# If satisfied, run with auto-fix
python test_portfolio_integrity_autofix.py
```

## What Gets Fixed

### Auto-Fixable Issues

| Issue | What's Fixed | Backup Created |
|-------|-------------|---|
| Missing `current_price` parameter in `reallocate()` | Method signature updated | ✓ Yes |
| Missing `current_price` parameter in `_allocate_capital()` | Method signature updated | ✓ Yes |
| Dashboard calculation formula missing | Code updated | ✓ Yes |

### Manual Review Required

These issues are **reported but not auto-fixed** (require deeper investigation):
- Capital consistency failures (indicates data corruption)
- Dashboard file missing entirely
- Database connectivity issues
- Binance API issues

## Troubleshooting

### Script Fails to Run
```bash
# Check Python version
python --version  # Should be 3.7+

# Check dependencies
python -c "import config; print('OK')"
```

### Backups Accumulating
All backups are safe to delete:
```bash
# Remove all backups
rm *.backup_*

# Or keep only recent ones
rm portfolio_manager.py.backup_202601*  # Delete Jan backups
```

### Need to Undo All Changes
```bash
# Find all backups
ls -lh *.backup_*

# Restore from latest backup of each file
cp portfolio_manager.py.backup_20260226_143022 portfolio_manager.py
cp dashboard/app.py.backup_20260226_143022 dashboard/app.py

# Restart bot
python main.py
```

## Integration with CI/CD

The script can be integrated into your development workflow:

### Run Before Deployment
```bash
# Test portfolio before deploying
python test_portfolio_integrity_autofix.py

# Only proceed if all tests pass
if [ $? -eq 0 ]; then
  python main.py
else
  echo "Tests failed!"
  exit 1
fi
```

### Continuous Testing
```bash
# Run tests every hour
while true; do
  python test_portfolio_integrity_autofix.py --no-fix
  sleep 3600
done
```

## Advanced Usage

### Custom Test Selection

You can modify the script to run specific tests:

```python
# Edit the file to comment out unwanted tests
run_all_tests(auto_fix=True)

# Or create a custom function
def run_critical_tests():
    results = []
    results.append(("Capital Consistency", test_capital_consistency()))
    results.append(("Dashboard Calculations", test_dashboard_calculations()))
    # ... etc
```

### Export Test Results

```bash
# Save output to file
python test_portfolio_integrity_autofix.py > test_results.txt 2>&1

# Share or archive
cat test_results.txt
```

## Support & Debugging

### Enable Detailed Logging
The script prints all intermediate steps. Look for:
- `✓ PASS` = Test passed
- `✗ FAIL` = Test failed
- `Backup created:` = File backed up before modification
- `Fixed successfully` = Issue resolved

### Common Issues

**Issue:** Tests fail even after auto-fix
- **Solution:** Restart the bot (`python main.py`)

**Issue:** Backups too large
- **Solution:** Delete old backups (`rm *.backup_*`)

**Issue:** Need to see what changed
- **Solution:** Compare with backup (`diff original.py original.py.backup_*)

## Summary

The auto-fix test script:
✓ Automatically detects issues
✓ Auto-fixes safe, simple problems
✓ Creates backups of all changes
✓ Reports clearly what was fixed
✓ Provides easy rollback if needed
✓ Helps keep your portfolio tool in top shape!

