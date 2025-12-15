import discord
import json
import base64
import os
import requests
import logging
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
    """Extract priority and type from anywhere in text"""
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
    """Understand natural language view requests"""
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
    """Create human-friendly display IDs that reset each time"""
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
    """Get tasks with proper filtering, sorting, and display IDs"""
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

    # Sort: normal first (oldest), then high (oldest)
    filtered.sort(key=lambda t: (
        0 if t['priority'] == 'normal' else 1, t['id']))

    display_map = generate_display_ids(filtered, status)

    return filtered, display_map


def resolve_task_id(display_id, context='personal'):
    """Convert display ID (T1, H2) or permanent ID (#107) to permanent ID"""
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


# Discord Bot Setup - NO PREFIX
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(''),
    intents=intents,
    help_command=None  # Disable default help so we can use our own
)


def is_authorized(ctx):
    if ctx.author.id != AUTHORIZED_USER:
        logging.warning(f"Unauthorized access attempt by {ctx.author.id}")
        return False
    return True


# Bot Events
@bot.event
async def on_ready():
    logging.info(f'{bot.user} ready - V5 Enhanced (No Prefix)')
    print(f'{bot.user} ready - V5 Enhanced (No Prefix)')


@bot.event
async def on_command(ctx):
    logging.info(f"COMMAND: {ctx.command.name} by {ctx.author}")


@bot.event
async def on_command_completion(ctx):
    logging.info(f"SUCCESS: {ctx.command.name} completed")


@bot.event
async def on_reaction_add(reaction, user):
    """Any reaction on any bot message shows tasks"""
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


# Helper to avoid repetition
def get_task_by_display_id(display_id, context='personal'):
    """Convert display ID to task and its list index"""
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
        "**Done:** `done <id>` or `d <id>`\n"
        "*Use display ID like T1, H2, or #107*\n\n"
        "**Edit:** `edit <id> <new text>`\n"
        "**Edit priority:** `edit <id> priority <high/normal>`\n"
        "**Delete:** `delete <id>`\n"
        "**Prio:** `prio <id> <high/normal>`\n\n"
        "**Tip:** React to any bot message to see tasks!"
    )
    await ctx.send(help_text)
    logging.info("Help command executed")


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
    if not args.strip():
        await ctx.send("❌ Usage: `done <id>` (e.g., T1, H2, or #107)")
        logging.warning("Done failed: no ID")
        return

    display_id = args.strip().split()[0]
    context = 'work' if 'work' in ctx.message.content.lower() else 'personal'
    task, index, error = get_task_by_display_id(display_id, context)

    if error:
        await ctx.send(f"❌ {error}")
        logging.warning(f"Done failed: {error}")
        return

    if task['completed']:
        await ctx.send(f"⚠️ Task #{task['id']} already completed")
        logging.info(f"Done failed: task {task['id']} already completed")
        return

    tasks = get_tasks()
    tasks[index]['completed'] = True
    tasks[index]['completed_at'] = datetime.now(
        timezone.utc).isoformat().replace('+00:00', 'Z')
    save_tasks(tasks)
    await ctx.send(f'✅ Completed task #{task["id"]}')
    logging.info(f"Completed task {task['id']}")


@bot.command(name='delete')
@commands.check(is_authorized)
async def delete_cmd(ctx, *, args: str = ''):
    if not args.strip():
        await ctx.send("❌ Usage: `delete <id>` (e.g., T1, H2, or #107)")
        logging.warning("Delete failed: no ID")
        return

    display_id = args.strip().split()[0]
    context = 'work' if 'work' in ctx.message.content.lower() else 'personal'
    task, index, error = get_task_by_display_id(display_id, context)

    if error:
        await ctx.send(f"❌ {error}")
        logging.warning(f"Delete failed: {error}")
        return

    tasks = get_tasks()
    removed = tasks.pop(index)
    save_tasks(tasks)
    await ctx.send(f'🗑️ Deleted task #{task["id"]}: "{removed["text"]}"')
    logging.info(f"Deleted task {task['id']}: {removed['text']}")


@bot.command(name='edit')
@commands.check(is_authorized)
async def edit_cmd(ctx, *, args: str = ''):
    parts = args.split(maxsplit=1)
    if len(parts) != 2:
        await ctx.send("❌ Usage: `edit <id> <new text>` or `edit <id> priority <high/normal>`")
        logging.warning("Edit failed: missing arguments")
        return

    display_id, action = parts

    # Handle priority change: edit 127 priority high
    if action.lower().startswith('priority') or action.lower().startswith('prio'):
        level = action.split()[-1]  # Get last word (high/normal)
        # Redirect to prio command
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


@bot.command(name='prio', aliases=['priority'])
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


# Run the bot
bot.run(DISCORD_TOKEN)
