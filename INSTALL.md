# Installation

## Option 1: Plugin install (recommended)

In Claude Code, run:

```
/plugin marketplace add illarion/claude-figma-skill
/plugin install claude-figma-skill
```

## Option 2: Manual install

Clone the repo and symlink the skill into your Claude Code skills directory:

```bash
git clone https://github.com/illarion/claude-figma-skill.git
mkdir -p ~/.claude/skills
ln -s "$(pwd)/claude-figma-skill/skills/figma" ~/.claude/skills/figma
```

## Setup

After installing, go to the root of your work folder, start a Claude Code session and do:
```
/figma login
```

The skill will guide you through authentication via interactive prompts. Follow the prompts to enter a project name and your Figma Personal Access Token.

After successful login, there will be `.figmaskillrc` created in this folder.

You can repeat this operation in other folders and associate them with other Figma tokens.

## Verify

Start a new Claude Code session and type `/figma` — the skill should appear.
