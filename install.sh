#!/usr/bin/env bash
# =============================================================================
# llm-relay — one-line installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/thatsbass/llm-relay/main/install.sh | bash
#
# NOTES:
#   - Use 'bash', not 'sh' — dash (Ubuntu's /bin/sh) does not support pipefail.
#   - Do NOT run with sudo. The script installs entirely into ~/.llm-relay/ as
#     your user and never needs elevated privileges itself.
#
# What this script does:
#   1. Verify Python >= 3.9 is available
#   2. Verify the venv module is available (exits with instructions if not)
#   3. Create a virtual environment in ~/.llm-relay/venv/
#   4. Install llm-relay from GitHub into the venv
#   5. Create a launcher script at ~/.local/bin/llm-relay
#   6. Add ~/.local/bin to PATH in the user's shell profile (if needed)
#   7. Launch the setup wizard
#
# Supported OS: macOS, Linux
# Supported shells: zsh, bash
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────

REPO="https://github.com/thatsbass/llm-relay"
INSTALL_DIR="$HOME/.llm-relay"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"
BINARY="$BIN_DIR/llm-relay"

# ── Colour helpers ────────────────────────────────────────────────────────────

_bold()  { printf "\033[1m%s\033[0m\n" "$1"; }
_ok()    { printf "  \033[32m✓\033[0m %s\n" "$1"; }
_warn()  { printf "  \033[33m⚠\033[0m %s\n" "$1"; }
_err()   { printf "  \033[31m✗\033[0m %s\n" "$1" >&2; exit 1; }
_step()  { printf "\n\033[1;34m▶ %s\033[0m\n" "$1"; }

# ── Step 1 — Detect Python >= 3.9 ────────────────────────────────────────────

_step "Checking Python"

PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            PYTHON="$cmd"
            version=$("$cmd" -c 'import sys; print(".".join(map(str,sys.version_info[:3])))')
            _ok "Found: $cmd ($version)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    _err "Python 3.9 or higher is required but was not found.
       Install it from https://python.org and re-run this script."
fi

# ── Step 2 — Verify venv support ─────────────────────────────────────────────
#
# On Ubuntu/Debian, Python is split into multiple packages.
# 'python3.12' does not bundle 'ensurepip' — you need 'python3.12-venv'.
# We check here, before touching any files, so the error is crystal-clear
# and the fix is a single copy-paste command.

_step "Checking venv support"

if ! "$PYTHON" -c "import ensurepip" 2>/dev/null; then
    py_ver="$("$PYTHON" -c 'import sys; v=sys.version_info; print(str(v.major)+"."+str(v.minor))')"
    printf "\n"
    printf "  \033[31m✗\033[0m Missing system package: python%s-venv\n\n" "$py_ver"
    printf "  Ubuntu/Debian ship the venv module as a separate apt package.\n"
    printf "  Run the following two commands, then re-run the installer:\n\n"
    printf "    \033[1msudo apt install python%s-venv\033[0m\n" "$py_ver"
    printf "    \033[1mcurl -fsSL https://raw.githubusercontent.com/thatsbass/llm-relay/main/install.sh | bash\033[0m\n\n"
    exit 1
fi

_ok "venv module available"

# ── Step 3 — Create directories ───────────────────────────────────────────────

_step "Setting up directories"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"
_ok "Created $INSTALL_DIR"

# ── Step 4 — Create / reuse virtual environment ───────────────────────────────

_step "Creating virtual environment"

# A previous failed install may have left a partial venv (directory exists but
# no bin/python inside). Remove it so this run starts fresh.
if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_DIR/bin/python" ]; then
    _warn "Removing incomplete venv from a previous install attempt..."
    rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR" \
        || _err "venv creation failed unexpectedly. Re-run the installer."
    _ok "Virtual environment created at $VENV_DIR"
else
    _ok "Reusing existing virtual environment"
fi

PYTHON_VENV="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ── Step 5 — Install llm-relay ────────────────────────────────────────────────

_step "Installing llm-relay"

"$PIP" install --quiet --upgrade pip
"$PIP" install --quiet "git+$REPO.git"
_ok "llm-relay installed"

# ── Step 6 — Create launcher script ───────────────────────────────────────────

_step "Creating launcher"

cat > "$BINARY" << LAUNCHER
#!/usr/bin/env bash
# llm-relay launcher — managed by install.sh, do not edit manually
exec "$PYTHON_VENV" -m llm_relay "\$@"
LAUNCHER

chmod +x "$BINARY"
_ok "Launcher created at $BINARY"

# ── Step 7 — Add ~/.local/bin to PATH ────────────────────────────────────────

_step "Configuring PATH"

# Detect which shell profile file to write to.
# Priority rules:
#   zsh  → .zshrc  (interactive) preferred; fall back to .zprofile (login)
#   bash → .bashrc (interactive) preferred; fall back to .bash_profile (login),
#           then .profile (POSIX fallback)
#   any  → .profile as last resort
_detect_profile() {
    local shell_name
    shell_name="$(basename "${SHELL:-sh}")"

    case "$shell_name" in
        zsh)
            # macOS Terminal opens login shells by default, so both files
            # may be needed.  .zshrc is the right choice for interactive
            # config (aliases, PATH, etc.).  Create it if absent.
            if [ -f "$HOME/.zshrc" ]; then
                echo "$HOME/.zshrc"
            elif [ -f "$HOME/.zprofile" ]; then
                echo "$HOME/.zprofile"
            else
                # Neither exists — prefer .zshrc (zsh standard).
                echo "$HOME/.zshrc"
            fi
            ;;
        bash)
            if [ -f "$HOME/.bashrc" ]; then
                echo "$HOME/.bashrc"
            elif [ -f "$HOME/.bash_profile" ]; then
                echo "$HOME/.bash_profile"
            elif [ -f "$HOME/.profile" ]; then
                echo "$HOME/.profile"
            else
                # No bash profile found — use .bashrc (Linux standard).
                echo "$HOME/.bashrc"
            fi
            ;;
        *)
            # Unknown shell (sh, fish, etc.) — use the POSIX fallback.
            if [ -f "$HOME/.profile" ]; then
                echo "$HOME/.profile"
            else
                echo ""
            fi
            ;;
    esac
}

# Check whether BIN_DIR is already in PATH (idempotent — never add twice).
# Uses a case pattern instead of read -ra (which is bash-only) so this
# function stays safe even when sourced in a mixed environment.
_path_has_bin_dir() {
    case ":${PATH}:" in
        *":${BIN_DIR}:"*) return 0 ;;
        *) return 1 ;;
    esac
}

if _path_has_bin_dir; then
    _ok "PATH already includes $BIN_DIR — nothing to do"
else
    PROFILE="$(_detect_profile)"

    if [ -n "$PROFILE" ]; then
        # Guard: don't append if the line is already there (re-run safety).
        if grep -q 'local/bin' "$PROFILE" 2>/dev/null; then
            _ok "PATH export already present in $PROFILE"
        else
            {
                printf '\n# Added by llm-relay installer\n'
                printf 'export PATH="$HOME/.local/bin:$PATH"\n'
            } >> "$PROFILE"
            _ok "Added ~/.local/bin to PATH in $(basename "$PROFILE")"
        fi
        _warn "Reload your shell for the change to take effect:"
        _warn "  source $PROFILE"
        _warn "  — or open a new terminal window."
    else
        _warn "Could not detect a shell profile file."
        _warn "Add this line manually to your shell config:"
        _warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────

printf "\n"
_bold "✓ Installation complete!"
printf "\n"
echo "  Starting setup wizard…"
printf "\n"

# Run setup wizard immediately.
"$BINARY" setup
