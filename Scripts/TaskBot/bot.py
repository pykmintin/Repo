import discord
import json
import base64
import os
import requests
import re
from datetime import datetime, timedelta
from discord.ext import commands

GITHUB_TOKEN = os.environ['GITHUB_TOKEN']
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'pykmintin/Repo')
DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
PREFIX = os.environ.get('PREFIX', '!')
AUTHORIZED_USER = int(os.environ.get('AUTHORIZED_USER', '0'))
TASKS_PATH = 'Scripts/TaskBot/tasks.json'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_REPO}/contents'


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


def parse_add(text):
    words = text.lower().split()
    priority = 'normal'
    task_type = 'personal'
    remaining = []

    for word in words:
        if word in ['high', 'h', 'urgent']:
            priority = 'high'
        elif word in ['work', 'w', 'corelink']:
            task_type = 'work'
        elif word in ['normal', 'n']:
            priority = 'normal'
        elif word in ['personal', 'p']:
            task_type = 'personal'
        else:
            remaining.append(word)

    return priority, task_type, ' '.join(remaining)


def parse_export(phrase):
    phrase = phrase.lower()
    now = datetime.utcnow()

    if 'tomorrow' in phrase:
        date = now + timedelta(days=1)
    elif 'today' in phrase:
        date = now
    else:
        return None, "Need phrase like 'tomorrow at 3pm'"

    time_match = re.search(r'at\s+(\d{1,2}(?::\d{2})?)\s*(am|pm)?', phrase)
    if time_match:
        time_str, period = time_match.groups()
        hour, minute = map(int, time_str.split(
            ':')) if ':' in time_str else (int(time_str), 0)
        if period == 'pm' and hour != 12:
            hour += 12
        date = date.replace(hour=hour, minute=minute, second=0)
        return date.isoformat() + 'Z', None
    return None, "What time?"


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)


def is_authorized(ctx):
    return ctx.author.id == AUTHORIZED_USER


@bot.command(name='add')
@commands.check(is_authorized)
async def add_cmd(ctx, *, text: str):
    text = text.strip()
    if text.lower().startswith('add '):
        text = text[4:].strip()

    priority, task_type, clean = parse_add(text)
    if not clean:
        return await ctx.send('❌ Need description')

    tasks = get_tasks()
    task_id = max([t['id'] for t in tasks], default=0) + 1
    task = {
        'id': task_id, 'text': clean, 'priority': priority, 'type': task_type,
        'completed': False, 'created_at': datetime.utcnow().isoformat() + 'Z', 'completed_at': None
    }
    tasks.append(task)
    save_tasks(tasks)

    icon = '🔴' if priority == 'high' else '⚪'
    ctx_icon = '🏠' if task_type == 'personal' else '💼'
    await ctx.send(f'{ctx_icon} ✅ #{task_id} [{icon}] {clean}')


@bot.command(name='tasks')
@commands.check(is_authorized)
async def tasks_cmd(ctx, filter: str = 'personal'):
    all_tasks = get_tasks()

    if filter == 'personal':
        tasks = [t for t in all_tasks if t['type'] == 'personal']
        title = '📋 Personal Tasks'
    elif filter == 'work':
        tasks = [t for t in all_tasks if t['type'] == 'work']
        title = '💼 Work Tasks'
    elif filter == 'all':
        tasks = all_tasks
        title = '📋 All Tasks'
    else:
        return await ctx.send('❌ Use: tasks / tasks work / tasks all')

    if not tasks:
        return await ctx.send(f'📭 No {filter} tasks')

    # Sort: high priority first, then incomplete before completed
    tasks.sort(key=lambda t: (0 if t['priority']
               == 'high' else 1, t['completed'], t['id']))

    lines = []
    for t in tasks:
        ctx_icon = '🏠' if t['type'] == 'personal' else '💼'
        prio_icon = '🔴' if t['priority'] == 'high' else '⚪'
        status_icon = '✅' if t['completed'] else '⏳'
        lines.append(
            f'{ctx_icon} {prio_icon} #{t["id"]} {status_icon} {t["text"]}')

    await ctx.send(f'**{title}**\n' + '\n'.join(lines))


@bot.command(name='complete')
@commands.check(is_authorized)
async def complete_cmd(ctx, task_id: int):
    tasks = get_tasks()
    for t in tasks:
        if t['id'] == task_id:
            t['completed'] = True
            t['completed_at'] = datetime.utcnow().isoformat() + 'Z'
            save_tasks(tasks)
            return await ctx.send(f'✅ #{task_id} completed')
    await ctx.send(f'❌ #{task_id} not found')


@bot.command(name='delete')
@commands.check(is_authorized)
async def delete_cmd(ctx, task_id: int):
    tasks = get_tasks()
    for i, t in enumerate(tasks):
        if t['id'] == task_id:
            removed = tasks.pop(i)
            save_tasks(tasks)
            return await ctx.send(f'🗑️ Deleted: #{task_id} "{removed["text"]}"')
    await ctx.send(f'❌ #{task_id} not found')


@bot.command(name='edit')
@commands.check(is_authorized)
async def edit_cmd(ctx, task_id: int, *, new_text: str):
    tasks = get_tasks()
    for t in tasks:
        if t['id'] == task_id:
            t['text'] = new_text
            save_tasks(tasks)
            return await ctx.send(f'✏️ #{task_id} updated: {new_text}')
    await ctx.send(f'❌ #{task_id} not found')


@bot.command(name='priority', aliases=['prio'])
@commands.check(is_authorized)
async def priority_cmd(ctx, task_id: int, level: str):
    level = level.lower()
    if level not in ['high', 'h', 'normal', 'n']:
        return await ctx.send('❌ Use: high/normal')
    priority = 'high' if level in ['high', 'h'] else 'normal'

    tasks = get_tasks()
    for t in tasks:
        if t['id'] == task_id:
            t['priority'] = priority
            save_tasks(tasks)
            return await ctx.send(f'🎯 #{task_id} priority set to {priority}')
    await ctx.send(f'❌ #{task_id} not found')


@bot.command(name='export')
@commands.check(is_authorized)
async def export_cmd(ctx, *, args: str):
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return await ctx.send('❌ Usage: export <id> <when>')

    task_id_str, phrase = parts
    date_result, error = parse_export(phrase)
    if error:
        return await ctx.send(f'❌ {error}')

    await ctx.send(f'📅 Export #{task_id_str} scheduled for {date_result}\n*(Google Calendar integration pending)*')


@bot.event
async def on_ready():
    print(f'{bot.user} ready - V4')

bot.run(DISCORD_TOKEN)
