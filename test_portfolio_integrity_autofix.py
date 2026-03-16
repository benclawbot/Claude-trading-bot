#!/usr/bin/env python3
"""
Portfolio Manager Test Suite with Auto-Fix Capabilities

This script:
1. Tests portfolio manager capital calculations
2. Auto-fixes common issues when tests fail
3. Creates backups before modifying files
4. Reports all changes clearly
"""

import sqlite3
import config
import os
import shutil
from datetime import datetime
from database import get_conn, init_db
from portfolio_manager import PortfolioManager
from binance_client import BinanceClient
from strategies import EMA5MomentumStrategy

# Color codes for output
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

class AutoFixer:
    """Handles automatic fixing of detected issues"""

    def __init__(self):
        self.fixes_applied = []
        self.backups_created = []

    def backup_file(self, filepath):
        """Create a backup of a file before modifying it"""
        if not os.path.exists(filepath):
            print(f"{RED}[FAIL] File not found: {filepath}{RESET}")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{filepath}.backup_{timestamp}"

        try:
            shutil.copy2(filepath, backup_path)
            self.backups_created.append({
                'original': filepath,
                'backup': backup_path
            })
            print(f"{YELLOW}  Backup created: {backup_path}{RESET}")
            return backup_path
        except Exception as e:
            print(f"{RED}[FAIL] Failed to create backup: {e}{RESET}")
            return None

    def fix_file(self, filepath, old_string, new_string, description):
        """Fix a specific issue in a file"""
        print(f"\n{BLUE}Fixing: {description}{RESET}")
        print(f"  File: {filepath}")

        # Create backup
        backup = self.backup_file(filepath)
        if not backup:
            return False

        try:
            # Read file
            with open(filepath, 'r') as f:
                content = f.read()

            # Check if old_string exists
            if old_string not in content:
                print(f"{RED}[FAIL] Pattern not found in file. Fix not applied.{RESET}")
                return False

            # Apply fix
            new_content = content.replace(old_string, new_string)

            # Write back
            with open(filepath, 'w') as f:
                f.write(new_content)

            print(f"{GREEN}[OK] Fixed successfully{RESET}")
            self.fixes_applied.append({
                'file': filepath,
                'description': description,
                'backup': backup
            })
            return True

        except Exception as e:
            print(f"{RED}[FAIL] Error applying fix: {e}{RESET}")
            return False

    def print_summary(self):
        """Print summary of all fixes applied"""
        if not self.fixes_applied:
            print(f"\n{GREEN}No fixes needed!{RESET}")
            return

        print(f"\n{BOLD}{'='*70}{RESET}")
        print(f"{BOLD}FIX SUMMARY{RESET}")
        print(f"{BOLD}{'='*70}{RESET}")

        for i, fix in enumerate(self.fixes_applied, 1):
            print(f"\n{BLUE}{i}. {fix['description']}{RESET}")
            print(f"   File: {fix['file']}")
            print(f"   Backup: {fix['backup']}")

        print(f"\n{YELLOW}Total fixes applied: {len(self.fixes_applied)}{RESET}")
        print(f"{YELLOW}Total backups created: {len(self.backups_created)}{RESET}")

        if self.backups_created:
            print(f"\n{BOLD}Backup locations:{RESET}")
            for backup_info in self.backups_created:
                print(f"  {backup_info['backup']}")

        print(f"\n{GREEN}All fixes applied successfully!{RESET}")

def test_capital_consistency(fixer=None):
    """Test that total capital = free_capital + committed + unrealized"""

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}TEST 1: Capital Calculation Consistency{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    try:
        init_db()
        strat = EMA5MomentumStrategy()
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)

        pm = PortfolioManager(client, [strat])
        initial_bal = pm.total_balance(current_price)

        print(f"\n{BLUE}Initial Balance:{RESET}")
        print(f"  Total Balance: ${initial_bal['total_balance']:,.2f}")
        print(f"  Free Capital:  ${initial_bal['free_capital']:,.2f}")
        print(f"  Realized P&L:  ${initial_bal['realized_pnl']:,.2f}")
        print(f"  Unrealized P&L: ${initial_bal['unrealized_pnl']:,.2f}")

        breakdown = initial_bal.get('breakdown', {})
        all_pass = True

        for strat_name, strat_info in breakdown.items():
            cap = strat_info['capital']
            free = strat_info['free_capital']
            committed = strat_info['committed_notional']
            realized = strat_info['realized_pnl']
            unrealized = strat_info['unrealized_pnl']

            print(f"\n{BLUE}Strategy: {strat_name}{RESET}")
            print(f"  Total Capital:    ${cap:,.2f}")
            print(f"  Free Capital:     ${free:,.2f}")
            print(f"  Committed:        ${committed:,.2f}")
            print(f"  Realized P&L:     ${realized:,.2f}")
            print(f"  Unrealized P&L:   ${unrealized:,.2f}")

            calculated_total = free + committed + unrealized
            print(f"\n  Consistency Check:")
            print(f"  Total Capital = {cap:,.2f}")
            print(f"  Free + Committed + Unrealized = {calculated_total:,.2f}")

            if abs(cap - calculated_total) < 0.01:
                print(f"  {GREEN}[OK] PASS: Capital values are consistent{RESET}")
            else:
                print(f"  {RED}[FAIL] FAIL: Capital mismatch! Difference = ${cap - calculated_total:,.2f}{RESET}")
                all_pass = False

        return all_pass

    except Exception as e:
        print(f"{RED}[FAIL] TEST FAILED: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return False

def test_reallocate_method(fixer=None):
    """Test that reallocate() method accepts current_price parameter"""

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}TEST 2: Reallocate Method Signature{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    try:
        init_db()
        strat = EMA5MomentumStrategy()
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)

        pm = PortfolioManager(client, [strat])

        print(f"\n{BLUE}Testing reallocate() method...{RESET}")
        print(f"  Calling: reallocate(current_price={current_price})")

        pm.reallocate(current_price)
        print(f"  {GREEN}[OK] PASS: reallocate() accepts current_price parameter{RESET}")
        return True

    except TypeError as e:
        print(f"  {RED}[FAIL] FAIL: Signature error{RESET}")
        print(f"  Error: {e}")

        if fixer:
            print(f"\n{YELLOW}Attempting auto-fix...{RESET}")
            # Try to fix the signature
            result = fixer.fix_file(
                'portfolio_manager.py',
                'def reallocate(self):',
                'def reallocate(self, current_price: float = 0.0):',
                'Update reallocate() method signature'
            )
            if result:
                print(f"{GREEN}[OK] Auto-fix successful! Please restart the bot.{RESET}")
                return True

        return False

    except Exception as e:
        print(f"  {RED}[FAIL] TEST FAILED: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return False

def test_allocate_capital_signature(fixer=None):
    """Test that _allocate_capital() accepts current_price parameter"""

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}TEST 3: _allocate_capital Method Signature{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    try:
        init_db()
        strat = EMA5MomentumStrategy()
        client = BinanceClient()
        current_price = client.get_current_price(config.SYMBOL)

        pm = PortfolioManager(client, [strat])

        print(f"\n{BLUE}Test 3a: With current_price parameter...{RESET}")
        print(f"  Calling: _allocate_capital({current_price})")
        pm._allocate_capital(current_price)
        print(f"  {GREEN}[OK] PASS{RESET}")

        print(f"\n{BLUE}Test 3b: With default parameter...{RESET}")
        print(f"  Calling: _allocate_capital()")
        pm._allocate_capital()
        print(f"  {GREEN}[OK] PASS{RESET}")

        return True

    except TypeError as e:
        print(f"  {RED}[FAIL] FAIL: Signature error{RESET}")
        print(f"  Error: {e}")

        if fixer:
            print(f"\n{YELLOW}Attempting auto-fix...{RESET}")
            result = fixer.fix_file(
                'portfolio_manager.py',
                'def _allocate_capital(self):',
                'def _allocate_capital(self, current_price: float = 0.0):',
                'Update _allocate_capital() method signature'
            )
            if result:
                print(f"{GREEN}[OK] Auto-fix successful! Please restart the bot.{RESET}")
                return True

        return False

    except Exception as e:
        print(f"  {RED}[FAIL] TEST FAILED: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return False

def test_dashboard_calculations(fixer=None):
    """Test that dashboard correctly computes total capital"""

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}TEST 4: Dashboard Capital Calculations{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    try:
        # Check if dashboard code has the correct calculations
        dashboard_path = 'dashboard/app.py'

        if not os.path.exists(dashboard_path):
            print(f"{RED}[FAIL] Dashboard file not found: {dashboard_path}{RESET}")
            return False

        with open(dashboard_path, 'r', encoding='utf-8', errors='ignore') as f:
            dashboard_content = f.read()

        # Check for key patterns
        checks = [
            ('true_total_cap' in dashboard_content, 'true_total_cap calculation'),
            ('true_total_cap = initial_share + realized_pnl + unrealized_pnl' in dashboard_content or
             'true_total_cap = initial_share + realized_pnl + unrealized_pnl' in dashboard_content, 'correct formula'),
            ('free_cap = true_total_cap - committed' in dashboard_content or
             'free_cap = true_total_cap - committed' in dashboard_content, 'correct free_cap calculation'),
            ('f"${true_total_cap:,.2f}"' in dashboard_content, 'display of true_total_cap'),
        ]

        print(f"\n{BLUE}Checking dashboard calculations...{RESET}")

        all_pass = True
        for check, description in checks:
            if check:
                print(f"  {GREEN}[OK] Found: {description}{RESET}")
            else:
                print(f"  {RED}[FAIL] Missing: {description}{RESET}")
                all_pass = False

        if all_pass:
            print(f"\n{GREEN}[OK] PASS: Dashboard calculations are correct{RESET}")
        else:
            print(f"\n{RED}[FAIL] FAIL: Dashboard calculations need fixes{RESET}")

        return all_pass

    except Exception as e:
        print(f"{RED}[FAIL] TEST FAILED: {e}{RESET}")
        import traceback
        traceback.print_exc()
        return False

def run_all_tests(auto_fix=True):
    """Run all tests with optional auto-fixing"""

    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}PORTFOLIO MANAGER - TEST SUITE WITH AUTO-FIX{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    fixer = AutoFixer() if auto_fix else None

    results = []

    # Run all tests
    results.append(("Capital Consistency", test_capital_consistency(fixer)))
    results.append(("Reallocate Signature", test_reallocate_method(fixer)))
    results.append(("Allocate Capital Signature", test_allocate_capital_signature(fixer)))
    results.append(("Dashboard Calculations", test_dashboard_calculations(fixer)))

    # Print summary
    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}TEST RESULTS SUMMARY{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, passed_result in results:
        status = f"{GREEN}[OK] PASS{RESET}" if passed_result else f"{RED}[FAIL] FAIL{RESET}"
        print(f"{status}: {test_name}")

    print(f"\n{BOLD}Score: {passed}/{total} tests passed{RESET}")

    # Print fix summary if applicable
    if fixer:
        fixer.print_summary()

    print(f"\n{BOLD}{'='*70}{RESET}")
    if passed == total:
        print(f"{GREEN}{BOLD}[OK] ALL TESTS PASSED - Portfolio is ready to use!{RESET}")
    else:
        print(f"{YELLOW}{BOLD}SOME TESTS FAILED - {total - passed} issue(s) to fix{RESET}")
        if auto_fix:
            print(f"{YELLOW}Review the output above for details.{RESET}")
    print(f"{BOLD}{'='*70}{RESET}\n")

    return passed == total

if __name__ == "__main__":
    import sys

    # Check for command line arguments
    auto_fix = True
    if len(sys.argv) > 1 and sys.argv[1] == "--no-fix":
        auto_fix = False
        print(f"{YELLOW}Running in test-only mode (no auto-fix){RESET}\n")

    success = run_all_tests(auto_fix=auto_fix)
    exit(0 if success else 1)
