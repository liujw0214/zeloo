#!/usr/bin/env bash
# bashcompinit helper for Zeloo CLI completion
# Source this from ~/.bashrc or ~/.bash_completion

# ── Subcommands ──────────────────────────────────────────────────────────────
_zeloo_subcommands() {
    printf '%s\n' chat config install doctor status backup model skills session mcp usage tools update oauth
}

# ── Config sub-actions ────────────────────────────────────────────────────────
_zeloo_config_actions() {
    printf '%s\n' show get set
}

# ── Main completion function ──────────────────────────────────────────────────
_zeloo_complete() {
    local cur prev words cword
    _init_completion || return

    local -A COMPREPLY_MAP
    local command subcommand

    # Determine if we are in a subcommand context
    for ((i = 1; i < cword; i++)); do
        case "${words[i]}" in
        chat|config|install|doctor|status|backup|model|skills|session|mcp|usage|tools|update|oauth)
            command="${words[i]}"
            break
            ;;
        esac
    done

    case "${command:-${cur}}" in
    chat)
        if [[ "${prev}" == "--model" || "${prev}" == "--provider" || "${prev}" == "--base-url" || "${prev}" == "--api-key" ]]; then
            return
        fi
        COMPREPLY_MAP["--model"]="Set LLM model (e.g. gpt-4o)"
        COMPREPLY_MAP["--provider"]="Set LLM provider (e.g. openai)"
        COMPREPLY_MAP["--base-url"]="Set base URL for compatible APIs"
        COMPREPLY_MAP["--api-key"]="Set API key"
        COMPREPLY_MAP["--max-iterations"]="Set max iterations"
        COMPREPLY_MAP["--temperature"]="Set temperature"
        COMPREPLY_MAP["--profile"]="Select profile"
        COMPREPLY_MAP["--verbose"]="Verbose logging"
        ;;

    config)
        if [[ "${prev}" == "action" ]]; then
            COMPREPLY_MAP["show"]="Show full configuration"
            COMPREPLY_MAP["get"]="Get a config value"
            COMPREPLY_MAP["set"]="Set a config value"
        elif [[ "${prev}" == "get" || "${prev}" == "set" ]]; then
            COMPREPLY_MAP["model"]="LLM model"
            COMPREPLY_MAP["provider"]="LLM provider"
            COMPREPLY_MAP["temperature"]="Sampling temperature"
            COMPREPLY_MAP["max_iterations"]="Max iterations"
            COMPREPLY_MAP["profile"]="Active profile"
        fi
        ;;

    install)
        COMPREPLY_MAP["--repair"]="Repair broken installation"
        COMPREPLY_MAP["--minimal"]="Skip optional dependency checks"
        ;;

    doctor)
        COMPREPLY_MAP["--fix"]="Automatically repair fixable issues"
        COMPREPLY_MAP["--json"]="Output results as JSON"
        ;;

    backup)
        COMPREPLY_MAP["--output"]="Output file path"
        COMPREPLY_MAP["--encrypt"]="Encrypt the backup"
        COMPREPLY_MAP["--include-secrets"]="Include credentials in backup"
        ;;

    model)
        COMPREPLY_MAP["--list"]="List available models"
        COMPREPLY_MAP["--set"]="Set default model"
        ;;

    skills)
        COMPREPLY_MAP["--list"]="List available skills"
        COMPREPLY_MAP["--install"]="Install a skill"
        COMPREPLY_MAP["--update"]="Update a skill"
        ;;

    session)
        COMPREPLY_MAP["--list"]="List sessions"
        COMPREPLY_MAP["--show"]="Show session details"
        COMPREPLY_MAP["--delete"]="Delete a session"
        COMPREPLY_MAP["--export"]="Export session"
        ;;

    mcp)
        COMPREPLY_MAP["--list"]="List MCP servers"
        COMPREPLY_MAP["--add"]="Add an MCP server"
        COMPREPLY_MAP["--remove"]="Remove an MCP server"
        COMPREPLY_MAP["--start"]="Start an MCP server"
        COMPREPLY_MAP["--stop"]="Stop an MCP server"
        ;;

    tools)
        COMPREPLY_MAP["--list"]="List available tools"
        COMPREPLY_MAP["--search"]="Search tools by name"
        ;;

    update)
        COMPREPLY_MAP["--check"]="Check for updates without installing"
        COMPREPLY_MAP["--force"]="Force reinstall even if up-to-date"
        ;;

    oauth)
        COMPREPLY_MAP["--list"]="List OAuth providers"
        COMPREPLY_MAP["--login"]="Login to a provider"
        COMPREPLY_MAP["--logout"]="Logout from a provider"
        ;;

    status|usage)
        COMPREPLY_MAP["--json"]="Output as JSON"
        ;;

    "")
        COMPREPLY_MAP["chat"]="Chat with the agent (default)"
        COMPREPLY_MAP["config"]="Show or modify configuration"
        COMPREPLY_MAP["install"]="Initialize or repair Zeloo environment"
        COMPREPLY_MAP["doctor"]="Diagnose configuration and dependency issues"
        COMPREPLY_MAP["status"]="Show agent, auth, and platform status"
        COMPREPLY_MAP["backup"]="Back up the Zeloo home directory"
        COMPREPLY_MAP["model"]="Show current model configuration"
        COMPREPLY_MAP["skills"]="List available skills"
        COMPREPLY_MAP["session"]="Manage sessions"
        COMPREPLY_MAP["mcp"]="Manage MCP servers"
        COMPREPLY_MAP["usage"]="Show API usage and cost reports"
        COMPREPLY_MAP["tools"]="List and inspect available tools"
        COMPREPLY_MAP["update"]="Check for and install updates"
        COMPREPLY_MAP["oauth"]="Manage OAuth logins for providers"
        COMPREPLY_MAP["--help"]="Show help"
        COMPREPLY_MAP["--version"]="Show version"
        COMPREPLY_MAP["--profile"]="Select a profile"
        COMPREPLY_MAP["--verbose"]="Verbose logging"
        ;;
    esac

    if [[ ${#COMPREPLY_MAP[@]} -gt 0 ]]; then
        local -a comps
        for key in "${!COMPREPLY_MAP[@]}"; do
            comps+=("${key}")
        done
        compopt -o nospace
        COMPREPLY=($(printf '%s\n' "${comps[@]}"))
    fi
}

complete -F _zeloo_complete zeloo
complete -F _zeloo_complete Zeloo
