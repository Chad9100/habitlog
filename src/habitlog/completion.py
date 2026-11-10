"""Shell completion scripts for bash, zsh and PowerShell.

The scripts are generated from the argparse parser, so new commands and options
are completed without maintaining a second list. Completion is static: it
offers commands, options and fixed choices (``--every``, ``--color`` ...), not
habit names.
"""

from __future__ import annotations

import argparse

SHELLS = ("bash", "zsh", "powershell")

# Global options that take a value: needed to find the command word.
_VALUE_OPTIONS_GLOBAL = ("--db", "--profile", "--color")


def collect(parser: argparse.ArgumentParser) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    """Return (global options, {command: options}, {option: fixed choices})."""
    sub_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    choices: dict[str, list[str]] = {}

    def options_of(p: argparse.ArgumentParser) -> list[str]:
        found: list[str] = []
        for action in p._actions:
            for opt in action.option_strings:
                if opt.startswith("--"):
                    found.append(opt)
                    if action.choices:
                        choices.setdefault(opt, [str(c) for c in action.choices])
        return sorted(set(found))

    commands = {name: options_of(sp) for name, sp in sub_action.choices.items()}
    return options_of(parser), commands, choices


def _join(items: list[str]) -> str:
    return " ".join(items)


def _bash(parser: argparse.ArgumentParser) -> str:
    glob, commands, choices = collect(parser)
    lines = [
        "# bash completion for habitlog",
        "# Load it with:  eval \"$(habitlog completion bash)\"",
        "_habitlog() {",
        "    local cur prev cmd i word",
        "    cur=\"${COMP_WORDS[COMP_CWORD]}\"",
        "    prev=\"${COMP_WORDS[COMP_CWORD-1]}\"",
        "    cmd=\"\"",
        "    for ((i = 1; i < COMP_CWORD; i++)); do",
        "        word=\"${COMP_WORDS[i]}\"",
        "        case \"$word\" in",
        f"            {'|'.join(_VALUE_OPTIONS_GLOBAL)}) ((i++)) ;;",
        "            -*) ;;",
        "            *) cmd=\"$word\"; break ;;",
        "        esac",
        "    done",
        "    case \"$prev\" in",
    ]
    for opt in sorted(choices):
        lines.append(f"        {opt}) COMPREPLY=($(compgen -W \"{_join(choices[opt])}\" -- \"$cur\")); return ;;")
    lines += [
        "    esac",
        "    if [[ -z \"$cmd\" ]]; then",
        f"        COMPREPLY=($(compgen -W \"{_join(sorted(commands))} {_join(glob)}\" -- \"$cur\"))",
        "        return",
        "    fi",
        "    case \"$cmd\" in",
    ]
    for name in sorted(commands):
        lines.append(f"        {name}) COMPREPLY=($(compgen -W \"{_join(commands[name])}\" -- \"$cur\")) ;;")
    lines += ["    esac", "}", "complete -o default -F _habitlog habitlog", ""]
    return "\n".join(lines)


def _zsh(parser: argparse.ArgumentParser) -> str:
    header = (
        "# zsh completion for habitlog\n"
        "# Load it with:  eval \"$(habitlog completion zsh)\"\n"
        "autoload -U +X bashcompinit && bashcompinit\n"
    )
    return header + _bash(parser).split("\n", 2)[2]


def _powershell(parser: argparse.ArgumentParser) -> str:
    glob, commands, choices = collect(parser)

    def arr(items: list[str]) -> str:
        return "@(" + ", ".join(f"'{i}'" for i in items) + ")"

    lines = [
        "# PowerShell completion for habitlog",
        "# Load it with:  habitlog completion powershell | Out-String | Invoke-Expression",
        "Register-ArgumentCompleter -Native -CommandName habitlog -ScriptBlock {",
        "    param($wordToComplete, $commandAst, $cursorPosition)",
        "    $words = @($commandAst.CommandElements | ForEach-Object { $_.ToString() })",
        f"    $valueOptions = {arr(list(_VALUE_OPTIONS_GLOBAL))}",
        "    $cmd = $null; $prev = $null",
        "    for ($i = 1; $i -lt $words.Count; $i++) {",
        "        if ($words[$i] -eq $wordToComplete -and $i -eq $words.Count - 1) { break }",
        "        $prev = $words[$i]",
        "        if ($valueOptions -contains $words[$i]) { $i++; $prev = $words[$i]; continue }",
        "        if (-not $words[$i].StartsWith('-')) { $cmd = $words[$i]; break }",
        "    }",
        "    if ($words.Count -ge 2 -and $wordToComplete -eq '') { $prev = $words[$words.Count - 1] }",
        "    elseif ($words.Count -ge 3) { $prev = $words[$words.Count - 2] }",
        "    $choices = @{",
    ]
    for opt in sorted(choices):
        lines.append(f"        '{opt}' = {arr(choices[opt])}")
    lines += ["    }", "    $commands = @{"]
    for name in sorted(commands):
        lines.append(f"        '{name}' = {arr(commands[name])}")
    lines += [
        "    }",
        f"    $global = {arr(sorted(commands) + glob)}",
        "    if ($prev -and $choices.ContainsKey($prev)) { $pool = $choices[$prev] }",
        "    elseif ($cmd -and $commands.ContainsKey($cmd)) { $pool = $commands[$cmd] }",
        "    else { $pool = $global }",
        "    $pool | Where-Object { $_ -like \"$wordToComplete*\" } | ForEach-Object {",
        "        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)",
        "    }",
        "}",
        "",
    ]
    return "\n".join(lines)


def script(shell: str, parser: argparse.ArgumentParser) -> str:
    """Return the completion script for ``shell`` (one of :data:`SHELLS`)."""
    if shell == "bash":
        return _bash(parser)
    if shell == "zsh":
        return _zsh(parser)
    if shell == "powershell":
        return _powershell(parser)
    raise ValueError(f"unsupported shell: {shell}")
