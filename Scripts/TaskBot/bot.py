import discord
import json
import base64
import os
import requests
import logging
import re
from datetime import datetime, timezone
from discord.ext import commands

# Setup logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')

# Configuration - NO PREFIX
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'pykmintin/Repo')
DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
AUTHORIZED_USER = int(os.environ.get('AUTHORIZED_USER', '0'))
TASKS_PATH = 'Scripts/TaskBot/tasks.json'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/contents'
MAX_BATCH_SIZE = 10


# GitHub Integration
def get_file_sha(path):
    url = f'{GITHUB_API}/{path}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    r = requests.get(url, headers=headers)
    return r.json().get('sha') if r.status_code == 200 else None


def github_put(path, content, message):
    url = f'{GITHUB_API}/{path}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    sha = get_file_sha(path)
    encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    data = {'message': message, 'content': encoded}
    if sha:
        data['sha'] = sha
    r = requests.put(url, headers=headers, json=data)
    r.raise_for_status()


def get_tasks():
    url = f'{GITHUB_API}/{TASKS_PATH}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    r = requests.get(url, headers=headers)
    if r.status_code == 404:
        save_tasks([])
        return []
    r.raise_for_status()
    return json.loads(base64.b64decode(r.json()['content']).decode('utf-8'))['tasks']


def save_tasks(tasks):
    content = json.dumps({'tasks': tasks}, indent=2)
    github_put(TASKS_PATH, content, 'Update tasks')


# Smart Natural Language Parsing
def parse_add(text):
    text_lower = text.lower()
    words = text.split()
    priority = 'normal'
    task_type = 'personal'
    remaining_words = []

    if any(word in text_lower for word in ['high', 'h', 'urgent', 'important']):
        priority = 'high'

    if any(word in text_lower for word in ['work', 'w', 'corelink', 'job']):
        task_type = 'work'

    skip_words = {'high', 'h', 'urgent', 'important', 'normal', 'n',
                  'work', 'w', 'corelink', 'job', 'personal', 'p'}

    for word in words:
        if word.lower() not in skip_words:
            remaining_words.append(word)

    return priority, task_type, ' '.join(remaining_words)


def parse_tasks_query(query):
    msg = query.lower() if query else ''

    if msg in ['a', 'all'] or 'all' in msg:
        status = 'all'
    elif msg in ['c', 'complete', 'completed'] or any(word in msg for word in ['complete', 'done', 'finished']):
        status = 'completed'
    elif msg in ['i', 'incomplete', 'pending']:
        status = 'incomplete'
    else:
        status = 'incomplete'

    if msg in ['h', 'high'] or 'high' in msg:
        context = 'high'
    elif msg in ['w', 'work'] or 'work' in msg:
        context = 'work'
    elif msg in ['p', 'personal'] or 'personal' in msg:
        context = 'personal'
    else:
        context = 'personal'

    return context, status


# Display ID System: T1-Tx, H1-Hx, C1-Cx
def generate_display_ids(tasks, status='incomplete'):
    display_map = {}

    if status == 'completed':
        for i, _ in enumerate(tasks):
            display_map[i] = f"C{i+1}"
    else:
        normal_count = 1
        high_count = 1
        for i, task in enumerate(tasks):
            if not task['completed']:
                if task['priority'] == 'high':
                    display_map[i] = f"H{high_count}"
                    high_count += 1
                else:
                    display_map[i] = f"T{normal_count}"
                    normal_count += 1

    return display_map


def get_filtered_tasks(context='personal', status='incomplete'):
    all_tasks = get_tasks()

    if context == 'work':
        filtered = [t for t in all_tasks if t['type'] == 'work']
    elif context == 'personal':
        filtered = [t for t in all_tasks if t['type'] == 'personal']
    elif context == 'high':
        filtered = [t for t in all_tasks if t['priority'] == 'high']
    else:
        filtered = all_tasks

    if status == 'incomplete':
        filtered = [t for t in filtered if not t['completed']]
    elif status == 'completed':
        filtered = [t for t in filtered if t['completed']]

    filtered.sort(key=lambda t: (
        0 if t['priority'] == 'normal' else 1, t['id']))
    display_map = generate_display_ids(filtered, status)

    return filtered, display_map


def resolve_task_id(display_id, context='personal'):
    if not display_id:
        return None

    if str(display_id).startswith('#') or str(display_id).isdigit():
        try:
            return int(str(display_id).replace('#', ''))
        except ValueError:
            return None

    display_id = str(display_id).strip().upper()
    tasks, display_map = get_filtered_tasks(context, 'incomplete')

    for i, task in enumerate(tasks):
        if display_map[i] == display_id:
            return task['id']

    if context == 'personal':
        tasks, display_map = get_filtered_tasks('work', 'incomplete')
        for i, task in enumerate(tasks):
            if display_map[i] == display_id:
                return task['id']

    return None


def get_task_by_display_id(display_id, context='personal'):
    if not display_id:
        return None, None, "Missing task ID"

    real_id = resolve_task_id(display_id, context)
    if not real_id:
        return None, None, f"Can't find task '{display_id}'. Use `tasks` to see IDs like T1, H2."

    tasks = get_tasks()
    for i, t in enumerate(tasks):
        if t['id'] == real_id:
            return t, i, None

    return None, None, f"Task #{real_id} not found"


# Discord Bot Setup - NO PREFIX, DISABLE DEFAULT HELP
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(''),
    intents=intents,
    help_command=None
)


def is_authorized(ctx):
    if ctx.author.id != AUTHORIZED_USER:
        logging.warning(f"Unauthorized access attempt by {ctx.author.id}")
        return False
    return True


# CRITICAL: Global error handler - ENSURES NOTHING FAILS SILENTLY
@bot.event
async def on_command_error(ctx, error):
    """Catch ALL command errors and respond with clear message"""
    if isinstance(error, commands.CommandNotFound):
        attempted = ctx.invoked_with
        cmd_map = {cmd.name.lower(): cmd for cmd in bot.commands}
        for cmd in bot.commands:
            for alias in cmd.aliases:
                cmd_map[alias.lower()] = cmd

        suggestions = [name for name in cmd_map.keys(
        ) if attempted and name.startswith(attempted[:2])]
        if suggestions:
            await ctx.send(f"❌ Unknown command: `{attempted}`. Did you mean: {', '.join(suggestions[:3])}?")
        else:
            await ctx.send(f"❌ Unknown command: `{attempted}`. Type `help` to see all commands.")
        logging.warning(f"Unknown command: {attempted} by {ctx.author}")

    elif isinstance(error, commands.CheckFailure):
        logging.warning(f"Authorization failed for {ctx.author}")
        # Silent for unauthorized users (your requirement)

    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}")
        logging.warning(f"Missing argument: {error} by {ctx.author}")

    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Bad argument: {str(error)}")
        logging.warning(f"Bad argument: {error} by {ctx.author}")

    else:
        error_msg = str(error) if len(
            str(error)) < 200 else str(error)[:200] + "..."
        await ctx.send(f"❌ Error: {error_msg}")
        logging.error(f"Command error: {error} by {ctx.author}")


# Bot Events
@bot.event
async def on_ready():
    logging.info(f'{bot.user} ready - V5 Enhanced (No Prefix, Batch Support)')
    print(f'{bot.user} ready - V5 Enhanced (No Prefix, Batch Support)')


@bot.event
async def on_command(ctx):
    logging.info(f"COMMAND: {ctx.command.name} by {ctx.author}")


@bot.event
async def on_command_completion(ctx):
    logging.info(f"SUCCESS: {ctx.command.name} completed")


@bot.event
async def on_reaction_add(reaction, user):
    if user.id != bot.user.id and reaction.message.author.id == bot.user.id:
        if user.id == AUTHORIZED_USER:
            logging.info(f"REACTION: {user} triggered task list")
            tasks, display_map = get_filtered_tasks('personal', 'incomplete')

            if not tasks:
                await reaction.message.channel.send("📭 No tasks")
                return

            lines = []
            for i, task in enumerate(tasks):
                ctx_icon = '🏠' if task['type'] == 'personal' else '💼'
                prio_icon = '🔴' if task['priority'] == 'high' else '⚪'
                display_id = display_map[i]
                lines.append(
                    f'{ctx_icon} {prio_icon} {display_id} {task["text"]}')

            await reaction.message.channel.send(f'**📋 Your Tasks**\n' + '\n'.join(lines))


# Commands
@bot.command(name='help', aliases=['h'])
@commands.check(is_authorized)
async def help_cmd(ctx):
    help_text = (
        "**TaskBot Commands** (no prefix needed, just type directly)\n\n"
        "**Add:** `add [h] <task>` or `a [h] <task>`\n"
        "*Shortcuts: h=high, w=work*\n\n"
        "**View:** `tasks` or `t`\n"
        "**View all:** `tasks all` or `t a`\n"
        "**View completed:** `tasks complete` or `t c`\n"
        "**View high only:** `tasks high` or `t h`\n\n"
        "**Done:** `done <id> [id2 id3...]` or `d <id>`\n"
        "**Delete:** `delete <id> [id2 id3...]`\n"
        "**Edit:** `edit <id> <new text>`\n"
        "**Edit priority:** `edit <id> priority <high/normal>`\n"
        "**Prio:** `prio <id> <high/normal>` or `edit prio <id> <value>`\n\n"
        "**Batch:** Use `;` or newlines for multiple commands (max 10)\n"
        "**Tip:** React to any bot message to see tasks!"
    )
    await ctx.send(help_text)


@bot.command(name='add', aliases=['a'])
@commands.check(is_authorized)
async def add_cmd(ctx, *, text: str = ''):
    if not text.strip():
        await ctx.send("❌ Need a task description")
        logging.warning("Add failed: no description")
        return

    text = text.strip()
    if text.lower().startswith('add '):
        text = text[4:].strip()

    priority, task_type, clean = parse_add(text)

    if not clean.strip():
        await ctx.send("❌ Couldn't find task description. Try: `add h Buy milk`")
        logging.warning("Add failed: no clean description")
        return

    tasks = get_tasks()
    task_id = max([t['id'] for t in tasks], default=99) + 1

    task = {
        'id': task_id,
        'text': clean,
        'priority': priority,
        'type': task_type,
        'completed': False,
        'created_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'completed_at': None
    }
    tasks.append(task)
    save_tasks(tasks)

    icon = '🔴' if priority == 'high' else '⚪'
    ctx_icon = '🏠' if task_type == 'personal' else '💼'
    await ctx.send(f'{ctx_icon} ✅ #{task_id} [{icon}] {clean}')
    logging.info(f"Added task {task_id}: {clean}")


@bot.command(name='tasks', aliases=['t'])
@commands.check(is_authorized)
async def tasks_cmd(ctx, *, query: str = ''):
    context, status = parse_tasks_query(query)
    tasks, display_map = get_filtered_tasks(context, status)

    if not tasks:
        status_word = "incomplete" if status == "incomplete" else status
        # FIXED: Matching quotes
        await ctx.send(f'📭 No {context} {status_word} tasks')
        logging.info(f"No tasks to display ({context}/{status})")
        return

    if context == 'high':
        title = '🔴 High Priority Tasks'
    elif context == 'work':
        title = '💼 Work Tasks'
    elif context == 'personal':
        title = '📋 Personal Tasks'
    else:
        title = '📋 All Tasks'

    lines = []
    for i, task in enumerate(tasks):
        ctx_icon = '🏠' if task['type'] == 'personal' else '💼'
        prio_icon = '🔴' if task['priority'] == 'high' else '⚪'
        status_icon = '✅' if task['completed'] else '⏳'
        display_id = display_map[i]
        lines.append(
            f'{ctx_icon} {prio_icon} {display_id} {status_icon} {task["text"]}')

    await ctx.send(f'**{title}**\n' + '\n'.join(lines))
    logging.info(f"Displayed {len(tasks)} tasks ({context}/{status})")


@bot.command(name='done', aliases=['d', 'complete'])
@commands.check(is_authorized)
async def done_cmd(ctx, *, args: str = ''):
    """Mark task(s) as complete. Resolves ALL IDs first, then applies changes atomically."""
    if not args.strip():
        await ctx.send("❌ Usage: `done <id> [id2 id3...]` (e.g., T1, H2, #107)")
        logging.warning("Done failed: no ID")
        return

    ids = args.strip().split()
    if len(ids) > 10:
        await ctx.send("❌ Max 10 tasks at once")
        return

    context = 'work' if 'work' in ctx.message.content.lower() else 'personal'

    # CRITICAL: Resolve ALL IDs against initial state BEFORE any modifications
    all_tasks = get_tasks()
    tasks_to_complete = []
    errors = []

    for display_id in ids:
        task, index, error = get_task_by_display_id(display_id, context)
        if error:
            errors.append(f"'{display_id}': {error}")
            continue

        if task['completed']:
            errors.append(f"'{display_id}': already completed")
            continue

        tasks_to_complete.append((task['id'], index))

    # Apply all changes atomically
    if tasks_to_complete:
        for real_id, task_index in tasks_to_complete:
            all_tasks[task_index]['completed'] = True
            all_tasks[task_index]['completed_at'] = datetime.now(
                timezone.utc).isoformat().replace('+00:00', 'Z')
            logging.info(f"Completed task {real_id}")

        save_tasks(all_tasks)

    # Report results
    results = [f"✅ #{real_id}" for real_id, _ in tasks_to_complete]
    if results:
        await ctx.send("**Completed:** " + " ".join(results))
    if errors:
        await ctx.send("**Skipped:** " + "\n".join(errors))


@bot.command(name='delete')
@commands.check(is_authorized)
async def delete_cmd(ctx, *, args: str = ''):
    """Delete task(s). Resolves ALL IDs first, then deletes in reverse order to preserve list indices."""
    if not args.strip():
        await ctx.send("❌ Usage: `delete <id> [id2 id3...]` (e.g., T1, H2, #107)")
        logging.warning("Delete failed: no ID")
        return

    ids = args.strip().split()
    if len(ids) > 10:
        await ctx.send("❌ Max 10 tasks at once")
        return

    context = 'work' if 'work' in ctx.message.content.lower() else 'personal'

    # CRITICAL: Resolve ALL IDs against initial state BEFORE any modifications
    all_tasks = get_tasks()
    tasks_to_delete = []
    errors = []

    for display_id in ids:
        task, index, error = get_task_by_display_id(display_id, context)
        if error:
            errors.append(f"'{display_id}': {error}")
            continue

        tasks_to_delete.append((task['id'], index, task['text']))

    # Apply all changes atomically in REVERSE order to preserve indices
    if tasks_to_delete:
        for real_id, task_index, _ in reversed(tasks_to_delete):
            removed = all_tasks.pop(task_index)
            logging.info(f"Deleted task {real_id}: {removed['text']}")

        save_tasks(all_tasks)

    # Report results
    results = [f"🗑️ #{real_id}" for real_id, _, _ in tasks_to_delete]
    if results:
        await ctx.send("**Deleted:** " + " ".join(results))
    if errors:
        await ctx.send("**Skipped:** " + "\n".join(errors))


@bot.command(name='edit', aliases=['e'])
@commands.check(is_authorized)
async def edit_cmd(ctx, *, args: str = ''):
    # Special case: edit prio h1 xxxxxx
    if args.lower().startswith('prio '):
        remaining = args[5:].strip()
        await ctx.invoke(bot.get_command('prio'), args=remaining)
        return

    parts = args.split(maxsplit=1)
    if len(parts) != 2:
        await ctx.send("❌ Usage: `edit <id> <new text>` or `edit <id> priority <high/normal>`")
        logging.warning("Edit failed: missing arguments")
        return

    display_id, action = parts

    # Handle priority change: edit 127 priority high
    if action.lower().startswith('priority ') or action.lower().startswith('prio '):
        level = action.split()[-1]
        await ctx.invoke(bot.get_command('prio'), args=f"{display_id} {level}")
        return

    # Regular text edit
    context = 'work' if 'work' in ctx.message.content.lower() else 'personal'
    task, index, error = get_task_by_display_id(display_id, context)
    if error:
        await ctx.send(f"❌ {error}")
        logging.warning(f"Edit failed: {error}")
        return

    tasks = get_tasks()
    old_text = tasks[index]['text']
    tasks[index]['text'] = action
    save_tasks(tasks)
    await ctx.send(f'✏️ Updated task #{task["id"]}:\n**Before:** {old_text}\n**After:** {action}')
    logging.info(f"Edited task {task['id']}: '{old_text}' → '{action}'")


@bot.command(name='prio', aliases=['priority', 'p'])
@commands.check(is_authorized)
async def prio_cmd(ctx, *, args: str = ''):
    parts = args.split(maxsplit=1)
    if len(parts) != 2:
        await ctx.send("❌ Usage: `prio <id> <high/normal>`")
        logging.warning("Prio failed: missing arguments")
        return

    display_id, level = parts
    level = level.lower()
    if level not in ['high', 'h', 'normal', 'n']:
        await ctx.send("❌ Use: high/normal (or h/n)")
        logging.warning(f"Prio failed: invalid level '{level}'")
        return

    priority = 'high' if level in ['high', 'h'] else 'normal'
    context = 'work' if 'work' in ctx.message.content.lower() else 'personal'
    task, index, error = get_task_by_display_id(display_id, context)
    if error:
        await ctx.send(f"❌ {error}")
        logging.warning(f"Prio failed: {error}")
        return

    tasks = get_tasks()
    old_prio = tasks[index]['priority']
    tasks[index]['priority'] = priority
    save_tasks(tasks)
    await ctx.send(f'🎯 Task #{task["id"]} priority: {old_prio} → {priority}')
    logging.info(
        f"Changed task {task['id']} priority: {old_prio} → {priority}")


# Smart Batching: Split on ; or newline, handle aliases, proper error handling
@bot.event
async def on_message(message):
    if message.author.id == bot.user.id:
        return

    if message.author.id != AUTHORIZED_USER:
        await bot.process_commands(message)
        return

    content = message.content.strip()

    # BUILD COMMAND MAP ONCE (includes all aliases)
    cmd_map = {}
    for cmd in bot.commands:
        cmd_map[cmd.name.lower()] = cmd
        for alias in cmd.aliases:
            cmd_map[alias.lower()] = cmd

    # Check if single command exists
    single_cmd_match = re.match(r'^(\w+)(\s+|$)', content)
    if single_cmd_match:
        cmd_name = single_cmd_match.group(1).lower()
        if cmd_name not in cmd_map:
            suggestions = [name for name in cmd_map.keys(
            ) if cmd_name and name.startswith(cmd_name[:2])]
            if suggestions:
                await message.channel.send(f"❌ Unknown command: `{cmd_name}`. Did you mean: {', '.join(suggestions[:3])}?")
            else:
                await message.channel.send(f"❌ Unknown command: `{cmd_name}`. Type `help` to see all commands.")
            logging.warning(f"Unknown command: {cmd_name} by {message.author}")
            return

    # Check for batch separators
    has_semicolon = ';' in content
    has_newline = '\n' in content

    if not (has_semicolon or has_newline):
        await bot.process_commands(message)
        return

    # Split and filter empty parts
    if has_semicolon:
        parts = [p.strip() for p in content.split(';') if p.strip()]
    else:
        parts = [p.strip() for p in content.split('\n') if p.strip()]

    if len(parts) <= 1:
        await bot.process_commands(message)
        return

    # Rate limiting
    if len(parts) > MAX_BATCH_SIZE:
        await message.channel.send(f"❌ Too many commands. Max {MAX_BATCH_SIZE} per message.")
        return

    # Process batch
    results = []
    errors = []
    tasks_modified = set()
    context_hint = 'personal'

    for i, part in enumerate(parts, 1):
        if len(part) > 2000:
            errors.append(f"Command {i} too long")
            continue

        cmd_match = re.match(r'^(\w+)(\s+|$)', part)
        if not cmd_match:
            errors.append(f"Command {i} invalid: {part[:50]}...")
            continue

        cmd_name = cmd_match.group(1).lower()
        command = cmd_map.get(cmd_name)

        if not command:
            suggestions = [name for name in cmd_map.keys(
            ) if cmd_name and name.startswith(cmd_name[:2])]
            if suggestions:
                errors.append(
                    f"Command {i} unknown: '{cmd_name}'. Did you mean: {', '.join(suggestions[:3])}?")
            else:
                errors.append(f"Command {i} unknown: '{cmd_name}'")
            continue

        args = part[len(cmd_name):].strip()

        # Conflict detection
        if command.name in ['edit', 'delete', 'prio', 'priority']:
            id_match = re.match(r'^(\S+)', args)
            if id_match:
                task_id = id_match.group(1)
                real_id = resolve_task_id(task_id, context_hint)
                if real_id and real_id in tasks_modified:
                    errors.append(
                        f"Command {i}: Task #{real_id} already modified")
                    continue
                if real_id:
                    tasks_modified.add(real_id)

        # Context tracking
        if 'work' in args.lower():
            context_hint = 'work'
        elif 'personal' in args.lower():
            context_hint = 'personal'

        # Execute with proper context.invoke
        try:
            ctx = await bot.get_context(message)

            # Pass context hint via message content override
            if command.name in ['tasks', 'done', 'delete', 'edit', 'prio']:
                ctx.message.content = f"{cmd_name} {args}"
                if context_hint == 'work' and 'work' not in args.lower():
                    ctx.message.content = f"{cmd_name} work {args}"

            if command.name in ['done', 'delete'] and args:
                id_list = args.split()
                if len(id_list) > 1:
                    for single_id in id_list:
                        sub_ctx = await bot.get_context(message)
                        sub_ctx.message.content = f"{cmd_name} {single_id}"
                        await ctx.invoke(command, args=single_id)
                    results.append(f"✓ {cmd_name} ({len(id_list)} tasks)")
                else:
                    await ctx.invoke(command, args=args)
                    results.append(f"✓ {part}")
            else:
                await ctx.invoke(command, args=args)
                results.append(f"✓ {part}")

        except Exception as e:
            error_str = str(e) if len(str(e)) < 100 else str(e)[:100] + "..."
            errors.append(f"Command {i} '{part[:30]}...': {error_str}")
            logging.error(f"Batch error {i}: {e}")

    # Send report
    if results or errors:
        report_lines = []
        if results:
            report_lines.append("**Success:**")
            for r in results:
                if len("\n".join(report_lines + [r])) > 1900:
                    remaining = len(results) - len(report_lines) + 1
                    report_lines.append(f"...and {remaining} more")
                    break
                report_lines.append(r)

        if errors:
            report_lines.append("\n**Errors:**")
            for e in errors:
                if len("\n".join(report_lines + [e])) > 1900:
                    remaining = len(errors) - len(report_lines) + 2
                    report_lines.append(f"...and {remaining} more")
                    break
                report_lines.append(e)

        report = "\n".join(report_lines).strip()
        await message.channel.send(report)

    return


# Run the bot
bot.run(DISCORD_TOKEN)
