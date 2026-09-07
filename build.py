"""
Build script for creating a standalone Windows executable using PyInstaller.

This script creates a single .exe file that includes all dependencies,
so the end user doesn't need Python installed.
"""

import os
import sys
import subprocess
import shutil

# Project directories
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ZAPRET_MANAGER_DIR = os.path.join(PROJECT_ROOT, "zapret_manager")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")


def clean_build_artifacts():
    """Remove previous build artifacts."""
    print("Cleaning previous build artifacts...")
    
    dirs_to_clean = [BUILD_DIR, DIST_DIR]
    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
            print(f"  Removed: {dir_path}")
    
    spec_file = os.path.join(PROJECT_ROOT, "ZapretManager.spec")
    if os.path.exists(spec_file):
        os.remove(spec_file)
        print(f"  Removed: {spec_file}")


def run_pyinstaller():
    """Run PyInstaller to create the executable."""
    print("\nRunning PyInstaller...")
    
    # PyInstaller command with all necessary options
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ZapretManager",
        "--onedir",  # Creates a folder with exe and dependencies
        "--windowed",  # No console window (GUI app)
        "--icon=NONE",  # Add icon path here if you have one
        "--add-data", f"{os.path.join(ZAPRET_MANAGER_DIR, '*.py')};zapret_manager/",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "tkinter.filedialog",
        "--collect-all", "tkinter",
        "--noconfirm",
        "--clean",
        os.path.join(ZAPRET_MANAGER_DIR, "__main__.py"),
    ]
    
    print(f"Command: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    
    if result.returncode != 0:
        print("\nERROR: PyInstaller failed!")
        return False
    
    print("\nPyInstaller completed successfully!")
    return True


def verify_build():
    """Verify that the executable was created."""
    exe_path = os.path.join(DIST_DIR, "ZapretManager", "ZapretManager.exe")
    
    if os.path.exists(exe_path):
        print(f"\n✓ Executable created successfully: {exe_path}")
        
        # Show size
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"  Size: {size_mb:.2f} MB")
        
        # List contents of dist folder
        print(f"\nContents of {DIST_DIR}:")
        for item in os.listdir(DIST_DIR):
            item_path = os.path.join(DIST_DIR, item)
            if os.path.isdir(item_path):
                files_count = sum(len(files) for _, _, files in os.walk(item_path))
                print(f"  📁 {item}/ ({files_count} files)")
            else:
                size_kb = os.path.getsize(item_path) / 1024
                print(f"  📄 {item} ({size_kb:.1f} KB)")
        
        return True
    else:
        print(f"\n✗ ERROR: Executable not found at {exe_path}")
        return False


def main():
    """Main build function."""
    print("=" * 60)
    print("ZapretManager - Build Script")
    print("=" * 60)
    
    # Check if running on Windows
    if sys.platform != "win32":
        print("\n⚠ WARNING: You're building on a non-Windows platform.")
        print("The resulting executable will only work on Windows.")
        print("For best results, run this script on Windows.\n")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("Build cancelled.")
            return False
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print(f"\n✓ PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("\n✗ PyInstaller is not installed!")
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller installed successfully")
    
    # Clean previous builds
    clean_build_artifacts()
    
    # Run PyInstaller
    if not run_pyinstaller():
        return False
    
    # Verify the build
    if not verify_build():
        return False
    
    print("\n" + "=" * 60)
    print("BUILD COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print(f"\nThe executable can be found in: {DIST_DIR}\\ZapretManager\\")
    print("\nTo distribute:")
    print("  1. Copy the entire ZapretManager folder from dist/")
    print("  2. Users can run ZapretManager.exe directly")
    print("  3. No Python installation required!")
    print("\nOptional: To create a single .exe file, use --onefile instead of --onedir")
    print("          Note: --onefile has slower startup time")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
