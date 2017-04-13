import inspect
import traceback
import asyncio
import shlex
import discord
import aiohttp
import json
import logging
import sys
import collections
import concurrent.futures

from TwitterAPI import TwitterAPI, TwitterRequestError, TwitterConnectionError


from io import BytesIO, StringIO
from datetime import datetime, timedelta
from textwrap import dedent
from itertools import islice

from .exceptions import CommandError
from .utils import clean_string, write_json, load_json, clean_bad_pings, datetime_to_utc_ts
VERSION = '1.0'

#logging.basicConfig(level=logging.DEBUG)

class Response(object):
    def __init__(self, content, reply=False, delete_after=0):
        self.content = content
        self.reply = reply
        self.delete_after = delete_after


class RhinoBot(discord.Client):
    def __init__(self):
        super().__init__()
        self.prefix = '!'
        self.token = 'PUT UR TOKEN HERE'
        self.tags = load_json('tags.json')
        self.tagblacklist = load_json('tagbl.json')
        self.twitch_watch_list = ['s3xualrhinoceros']
        self.autist_list = load_json('autism.json')
        self.weeb_list = load_json('weeb.json')
        self.twitch_is_live = {}
        self.server_whitelist = load_json('server_whitelist.json')
        self.twitch_client_id = 'TWITCH API KEY HERE'
        self.twitch_debug = True
        self.since_id = {'SexualRhino_': 826248627739885568}
        self.twitAPI = TwitterAPI('CONSUMER KEY',
                                  'CONSUMER PRIV',
                                  'APP KEY',
                                  'APP PRIV')
        print('past init')

    # noinspection PyMethodOverriding
    def run(self):
        loop = asyncio.get_event_loop()
        try:
            loop.create_task(self.get_tweets())
            loop.create_task(self.check_twitch_streams())
            loop.run_until_complete(self.start(self.token))
            loop.run_until_complete(self.connect())
        except Exception:
            loop.run_until_complete(self.close())
            pending = asyncio.Task.all_tasks()
            gathered = asyncio.gather(*pending)
            try:
                gathered.cancel()
                loop.run_forever()
                gathered.exception()
            except:
                pass
        finally:
            loop.close()
            

            
    async def get_tweets(self):
        await self.wait_until_ready()
        
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        loop = asyncio.get_event_loop()
        
        def get_twitter_data():
            return self.twitAPI.request('statuses/user_timeline', {'screen_name': 'SexualRhino_',
                                                                    'exclude_replies': True,
                                                                    'include_rts': False,
                                                                    'count': 1})
            
        future = loop.run_in_executor(executor, get_twitter_data)
        
        r = await future
        for item in r.get_iterator():
            print('in ID 1')
            if item['id'] > self.since_id['SexualRhino_']:
                self.since_id['SexualRhino_'] = item['id']
                
        while not self.is_closed:
            try:
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
                loop = asyncio.get_event_loop()
                future = loop.run_in_executor(executor, get_twitter_data)
                
                r = await future
                for item in r.get_iterator():
                    if 'text' in item and item['id'] > self.since_id['SexualRhino_']:
                        self.since_id['SexualRhino_'] = item['id']
                        embed = await self.generate_tweet_embed(item)
                        await self.safe_send_message(discord.Object(id='298778712709529603'), embed=embed)
                await asyncio.sleep(1.5)
            except TwitterRequestError as e:
                if e.status_code < 500:
                    print(e.status_code)
                    print('something needs to be fixed before re-connecting')
                    await asyncio.sleep(60)
                else:
                    print('temporary interruption, re-try request')
                    pass
            except TwitterConnectionError:
                print('temporary interruption, re-try request')
                pass
            
    async def generate_tweet_embed(self, resp):
        final_text = None
        image_url = None
        
        if 'media' in resp["entities"]:
            if len(resp["entities"]["media"]) == 1:
                for media in resp["entities"]["media"]:
                    if not final_text:
                        final_text = clean_string(resp["text"]).replace(media["url"], '')
                    else:
                        final_text = final_text.replace(media["url"], '')
                    image_url = media["media_url_https"]
        if 'urls' in resp["entities"]:
            for url in resp["entities"]["urls"]:
                if not final_text:
                    final_text = clean_string(resp["text"]).replace(url["url"], '[{0}]({1})'.format(url["display_url"], url["expanded_url"]))
                else:
                    final_text = final_text.replace(url["url"], '[{0}]({1})'.format(url["display_url"], url["expanded_url"]))
        if not final_text:
            final_text = clean_string(resp["text"])
        
        if 'in_reply_to_screen_name' in resp and resp["in_reply_to_screen_name"] == 'SexualRhino_':
            final_text = '➡ ' + final_text
            
        date_time = datetime.strptime(resp["created_at"], "%a %b %d %H:%M:%S +0000 %Y")
        em = discord.Embed(colour=discord.Colour(0x00aced), description=final_text, timestamp=date_time)
        if image_url:
            em.set_image(url=image_url)
        em.set_author(name=resp["user"]['screen_name'], url='https://twitter.com/{}/status/{}'.format(resp["user"]["screen_name"], resp["id"]), icon_url=resp["user"]["profile_image_url_https"])
        return em
        
    async def generate_streaming_embed_online(self, resp, streamer):
        em = discord.Embed(colour=discord.Colour(0x56d696), description=resp["stream"]["channel"]["status"], timestamp=datetime.strptime(resp["stream"]["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        em.set_image(url=str(resp["stream"]["preview"]["large"]))
        em.set_author(name=streamer, url='https://www.twitch.tv/{}'.format(streamer), icon_url=resp["stream"]["channel"]["logo"])
        em.set_footer(text="Language: {}".format(resp["stream"]["channel"]["language"].upper()))

        em.add_field(name="Status", value="LIVE", inline=True)
        em.add_field(name="Viewers", value=resp["stream"]["viewers"], inline=True)
        return em      
        
    async def generate_streaming_embed_offline(self, resp, streamer):
        em = discord.Embed(colour=discord.Colour(0x979c9f), description=resp["status"], timestamp=datetime.strptime(resp["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
        em.set_image(url=str(resp["video_banner"]))
        em.set_author(name=streamer, url='https://www.twitch.tv/{}'.format(streamer), icon_url=resp["logo"])
        em.set_footer(text="Language: {}".format(resp["language"].upper()))

        em.add_field(name="Status", value="OFFLINE", inline=True)
        em.add_field(name="Viewers", value='0', inline=True)
        return em
               
    async def check_twitch_streams(self):
        await self.wait_until_ready()
        if self.twitch_debug: print('starting stream function')
        def is_me(m):
            return m.author == self.user
        await self.purge_from(discord.Object(id='299133385681666049'), limit=100, check=is_me)
        if self.twitch_debug: print('starting stream function')
        while True:
            for streamer in self.twitch_watch_list:
                try:
                    with aiohttp.ClientSession() as session:
                        await asyncio.sleep(1)
                        resp = None
                        async with session.get('https://api.twitch.tv/kraken/streams/{}?client_id={}'.format(streamer, self.twitch_client_id)) as r:
                            try:
                                resp = await r.json()
                            except json.decoder.JSONDecodeError:
                                pass
                        if resp and resp["stream"]:
                            if streamer not in self.twitch_is_live:
                                role = discord.utils.get(discord.utils.get(self.servers, id='298778712709529603').roles, id='298781003051302912')
                                await self.edit_role(discord.utils.get(self.servers, id='298778712709529603'), role, mentionable=True)
                                if self.twitch_debug: print('Creating new online embed for user %s' % streamer)
                                self.twitch_is_live[streamer] = {'detected_start': datetime.utcnow(),
                                                                 'view_count_updated': datetime.utcnow(),
                                                                 'offline_cooldown': False,
                                                                 'embedded_object': await self.generate_streaming_embed_online(resp, streamer),
                                                                 'message': None}
                                self.twitch_is_live[streamer]['message'] = await self.safe_send_message(discord.Object(id='299133385681666049'), content='%s' % role.mention, embed=self.twitch_is_live[streamer]['embedded_object'])
                                await self.edit_role(discord.utils.get(self.servers, id='298778712709529603'), role, mentionable=False)
                            else:
                                if datetime.utcnow() - timedelta(minutes=15) > self.twitch_is_live[streamer]['detected_start']:
                                    if self.twitch_debug: print('Recreating new embed for user %s' % streamer)
                                    role = discord.utils.get(discord.utils.get(self.servers, id='298778712709529603').roles, id='298781003051302912')
                                    await self.edit_role(discord.utils.get(self.servers, id='298778712709529603'), role, mentionable=True)
                                    await self.safe_delete_message(self.twitch_is_live[streamer]['message'])
                                    self.twitch_is_live[streamer] = {'detected_start': datetime.utcnow(),
                                                                     'view_count_updated': datetime.utcnow(),
                                                                     'offline_cooldown': False,
                                                                     'embedded_object': await self.generate_streaming_embed_online(resp, streamer),
                                                                     'message': None}
                                    self.twitch_is_live[streamer]['message'] = await self.safe_send_message(discord.Object(id='299133385681666049'), content='%s' % role.mention, embed=self.twitch_is_live[streamer]['embedded_object'])
                                    await self.edit_role(discord.utils.get(self.servers, id='298778712709529603'), role, mentionable=False)
                                elif datetime.utcnow() - timedelta(minutes=5) > self.twitch_is_live[streamer]['view_count_updated']:
                                    if self.twitch_debug: print('Updating embeds view count for user %s' % streamer)
                                    self.twitch_is_live[streamer]['embedded_object'] = await self.generate_streaming_embed_online(resp, streamer)
                                    self.twitch_is_live[streamer]['view_count_updated'] = datetime.utcnow()
                                    await self.safe_edit_message(self.twitch_is_live[streamer]['message'], embed=self.twitch_is_live[streamer]['embedded_object'])
                                    
                        elif streamer in self.twitch_is_live and not self.twitch_is_live[streamer]['offline_cooldown']:
                            if self.twitch_debug: print('User %s detected offline, marking as such' % streamer)
                            self.twitch_is_live[streamer]['embedded_object'].color = discord.Colour(0x979c9f)
                            self.twitch_is_live[streamer]['embedded_object'].set_field_at(0, name="Status", value="OFFLINE", inline=True)
                            self.twitch_is_live[streamer]['offline_cooldown'] = True
                            await self.safe_edit_message(self.twitch_is_live[streamer]['message'], embed=self.twitch_is_live[streamer]['embedded_object'])
                        elif streamer not in self.twitch_is_live:
                            async with session.get('https://api.twitch.tv/kraken/channels/{}?client_id={}'.format(streamer, self.twitch_client_id)) as r:
                                try:
                                    resp = await r.json()
                                except json.decoder.JSONDecodeError:
                                    pass
                            if self.twitch_debug: print('Creating new offline embed for user %s' % streamer)
                            self.twitch_is_live[streamer] = {'detected_start': datetime.utcnow(),
                                                             'view_count_updated': datetime.utcnow(),
                                                             'offline_cooldown': True,
                                                             'embedded_object': await self.generate_streaming_embed_offline(resp, streamer),
                                                             'message': None}
                            self.twitch_is_live[streamer]['message'] = await self.safe_send_message(discord.Object(id='299133385681666049'), embed=self.twitch_is_live[streamer]['embedded_object'])
                            
                except:
                    print('error within twitch loop, handled to prevent breaking')
                    traceback.print_exc()
                    
    async def on_ready(self):
        print('Connected!\n')
        print('Username: %s' % self.user.name)
        print('Bot ID: %s' % self.user.id)
        
        await self.change_presence(game=discord.Game(name='Playing Playing Playing Playing Playing Playing...'))
        
        if self.servers:
            print('--Server List--')
            [print(s) for s in self.servers]
        else:
            print("No servers have been joined yet.")

        print()

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    async def safe_send_message(self, dest, *, content=None, tts=False, expire_in=0, quiet=False, embed=None):
        msg = None
        try:
            msg = await self.send_message(dest, content=content, tts=tts, embed=embed)

            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

        except discord.Forbidden:
            if not quiet:
                print("Error: Cannot send message to %s, no permission" % dest.name)
        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot send message to %s, invalid channel?" % dest.name)
        finally:
            if msg: return msg

    async def safe_delete_message(self, message, *, quiet=False):
        try:
            return await self.delete_message(message)

        except discord.Forbidden:
            if not quiet:
                print("Error: Cannot delete message \"%s\", no permission" % message.clean_content)
        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot delete message \"%s\", message not found" % message.clean_content)

    async def safe_edit_message(self, message, *, new_content=None, expire_in=0, send_if_fail=False, quiet=False, embed=None):
        msg = None
        try:
            if not embed:
                msg = await self.edit_message(message, new_content=new_content)
            else:
                msg = await self.edit_message(message, new_content=new_content, embed=embed)

            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

        except discord.NotFound:
            if not quiet:
                print("Warning: Cannot edit message \"%s\", message not found" % message.clean_content)
            if send_if_fail:
                if not quiet:
                    print("Sending instead")
                msg = await self.safe_send_message(message.channel, content=new)
        finally:
            if msg: return msg

    async def cmd_whitelistserver(self, author, server_id):
        """
        Usage: {command_prefix}whitelistserver server_id
        Adds a server's id to the whitelist!
        """
        if [role for role in author.roles if role.id  in ["298781054909546497", "298780936823373824", "299112346402553857"]]:
            if server_id not in self.server_whitelist:
                self.server_whitelist.append(server_id)
                write_json('server_whitelist.json', self.server_whitelist)
                return Response(':thumbsup:', reply=True)

    async def cmd_restart(self, channel, author):
        """
        Usage: {command_prefix}restart
        Forces a restart
        """
        if [role for role in author.roles if role.id  in ["298781054909546497", "298780936823373824", "299112346402553857"]]:
            await self.safe_send_message(message.channel, content="Restarting....")
            await self.logout()

    async def cmd_changeavi(self, author, string_avi):
        """
        Usage: {command_prefix}changeavi ["image url"]
        Changes the avatar of the bot
        """
        
        if [role for role in author.roles if role.id  in ["298781054909546497", "298780936823373824", "299112346402553857"]]:
            async with aiohttp.get(string_avi) as r:
                data = await r.read()
                await self.edit_profile(avatar=data)
            return Response(':thumbsup:', reply=True)

    async def cmd_eval(self, author, server, message, channel, mentions, code):
        """
        Usage: {command_prefix}eval "evaluation string"
        runs a command thru the eval param for testing
        """
        if author.id != '77511942717046784':
            return
        python = '```py\n{}\n```'
        result = None

        try:
            result = eval(code)
        except Exception as e:
            return Response(python.format(type(e).__name__ + ': ' + str(e)))

        if asyncio.iscoroutine(result):
            result = await result

        return Response('```{}```'.format(result))

    async def cmd_exec(self, author, server, message, channel, mentions, code):
        """
        Usage: {command_prefix}eval "evaluation string"
        runs a command thru the eval param for testing
        """
        if author.id != '77511942717046784':
            return
        old_stdout = sys.stdout
        redirected_output = sys.stdout = StringIO()

        try:
            exec(code)
        except Exception:
            formatted_lines = traceback.format_exc().splitlines()
            return Response('```py\n{}\n{}\n```'.format(formatted_lines[-1], '\n'.join(formatted_lines[4:-1])), reply=True)
        finally:
            sys.stdout = old_stdout

        if redirected_output.getvalue():
            return Response(redirected_output.getvalue(), reply=True)
        return Response(':thumbsup:', reply=True)

    async def cmd_changegame(self, author, string_game):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playing..." game on Discord!
        """
        await self.change_presence(game=discord.Game(name=string_game))
        return Response(':thumbsup:', reply=True)
        
    async def cmd_tag(self, message, author, channel, mentions, leftover_args):
        """
        Usage {command_prefix}tag tag name
        Gets a tag from the database of tags and returns it in chat for all to see.
        
        Usage {command_prefix}tag list
        Sends you a PM listing all tags in the tag database
        
        Usage {command_prefix}tag [+, add, -, remove,  blacklist]
        Mod only commands, ask rhino if you dont know the full syntax
        """
        if int(author.id) in self.tagblacklist:
            return
        switch = leftover_args.pop(0).lower()
        if switch in ['+', 'add', '-', 'remove', 'list', 'blacklist']:
            if switch in ['+', 'add']:
                if [role for role in author.roles if role.id  in ["299112346402553857", "298781131925487617", "298781148752904193", "298781054909546497", "298781093128175626", "298780936823373824", "298881590761619457"]]:
                    if len(leftover_args) == 2:
                        if len(leftover_args[0]) > 200 or len(leftover_args[1]) > 1750:
                            raise CommandError('Tag length too long')
                        self.tags[leftover_args[0].lower()] = [False, leftover_args[1]]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" created' % clean_bad_pings(leftover_args[0]), delete_after=15)
                    elif len(leftover_args) == 3 and 'restrict' in leftover_args[0]:
                        if len(leftover_args[1]) > 200 or len(leftover_args[2]) > 1750:
                            raise CommandError('Tag length too long')
                        self.tags[leftover_args[1].lower()] = [True, leftover_args[2]]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" created' % clean_bad_pings(leftover_args[1]), delete_after=15)
                        
                    else:
                        print(leftover_args)
                        raise CommandError('Bad input')
            elif switch == 'list':
                try:
                    this = sorted(list(self.tags.keys()), key=str.lower)
                    new_this = [this[0]]
                    for elem in this[1:]:
                        if len(new_this[-1]) + len(elem) < 70:
                            new_this[-1] = new_this[-1] + ', ' + elem
                        else:
                            new_this.append(elem)
                    final = clean_bad_pings('%s' % '\n'.join(new_this))
                    if len(final) > 1800:
                        final_this = [new_this[0]]
                        for elem in new_this[1:]:
                            if len(final_this[-1]) + len(elem) < 1800:
                                final_this[-1] = final_this[-1] + '\n' + elem
                            else:
                                final_this.append(elem)
                        for x in final_this:
                            await self.safe_send_message(author, content=x)
                    else:
                        await self.safe_send_message(author, content=final)
                except Exception as e:
                    print(e)
            elif switch == 'blacklist':
                if [role for role in author.roles if role.id  in ["299112346402553857", "298781131925487617", "298781148752904193", "298781054909546497", "298781093128175626", "298780936823373824", "298881590761619457"]]:
                    for user in mentions:
                        self.tagblacklist.append(int(user.id))
                        return Response('User `{}` was blacklisted'.format(clean_bad_pings(user.name)), delete_after=20)
            else:
                if [role for role in author.roles if role.id  in ["299112346402553857", "298781131925487617", "298781148752904193", "298781054909546497", "298781093128175626", "298780936823373824", "298881590761619457"]]:
                    try:
                        del self.tags[' '.join(leftover_args)]
                        write_json('tags.json', self.tags)
                        return Response('Tag \"%s\" removed' % clean_bad_pings(' '.join(leftover_args)), delete_after=10)
                    except:
                        raise CommandError('Tag doesn\'t exist to be removed')
        else:
            msg = False
            if leftover_args:
                tag_name = '{} {}'.format(switch, ' '.join(leftover_args))
            else:
                tag_name = switch
            for tag in self.tags:
                if tag_name.lower() == tag.lower():
                    if self.tags[tag][0]:
                        if not [role for role in author.roles if role.id  in ["299112346402553857", "298781131925487617", "298781148752904193", "298781054909546497", "298781093128175626", "298780936823373824", "298881590761619457"]]:
                            return Response('Tag cannot be used by nonstaff members')
                    return Response(clean_bad_pings(self.tags[tag][1]))
            raise CommandError('Tag doesn\'t exist')
    
    async def cmd_ping(self, message, author, server):
        """
        Usage: {command_prefix}ping
        Replies with "PONG!"; Use to test bot's responsiveness
        """
        return Response('PONG!!!', reply=True)
        
    async def cmd_cmdinfo(self, author, command=None):
        """
        Usage:{command_prefix}cmdinfo [command]
        Prints a help message.
        If a command is specified, it prints a help message for that command.
        Otherwise, it lists the available commands.
        """
        if command:
            cmd = getattr(self, 'cmd_' + command, None)
            if cmd:
                return Response("```\n{}```".format(dedent(cmd.__doc__).format(command_prefix=self.prefix)))
            else:
                return Response("No such command")

        else:
            helpmsg = "**Commands**\n```"
            commands = []

            for att in dir(self):
                if att.startswith('cmd_') and att != 'cmd_help':
                    command_name = att.replace('cmd_', '').lower()
                    commands.append("{}{}".format(self.prefix, command_name))

            helpmsg += ", ".join(commands)
            helpmsg += "```"

            return Response(helpmsg, reply=True)

    async def cmd_help(self, message, server, channel):
        """
        Usage {command_prefix}help
        Fetches the help info for the bot's commands I swear
        """
        final_role_names = ', '.join([rc.name for rc in server.roles if rc.id not in LOCK_ROLES and not rc.is_everyone])
        unhelpful_response = random.choice(['As I See It Yes', 'Ask Again Later', 'Better Not Tell You Now', 'Cannot Predict Now',
                       'Concentrate and Ask Again', 'Don\'t Count On It', 'It Is Certain', 'It Is Decidely So',
                       'Most Likely', 'My Reply Is No', 'My Sources Say No', 'Outlook Good', 'Outlook Not So Good', 
                       'Reply Hazy Try Again', 'Signs Point to Yes', 'Very Doubtful', 'Without A Doubt', 'Yes', 'Yes - Definitely', 'You May Rely On It'])
        return Response(unhelpful_response, delete_after=120)

    async def cmd_echo(self, author, message, server, channel, leftover_args):
        """
        Usage {command_prefix}echo #channel "ENTER MESSAGE HERE"
        Fetches the help info for the bot's commands
        """
        if [role for role in author.roles if role.id  in ["298781054909546497", "298780936823373824", "299112346402553857"]]:
            chan_mentions = message.channel_mentions
            for chan in chan_mentions:
                await self.safe_send_message(chan, content=' '.join(leftover_args))
            return Response(':thumbsup:')
            
    async def on_member_join(self, member):
        if member.server.id == '159915737480298496':
            if not member.id == '80351110224678912':
                member_roles = [discord.utils.get(member.server.roles, id='260520774388023297')]
                if member_roles:
                    await self.replace_roles(member, *member_roles)
        if member.server.id == '298778712709529603':
            if not member.id == '80351110224678912':
                member_roles = [discord.utils.get(member.server.roles, id='298781003051302912')]
                if member_roles:
                    await self.replace_roles(member, *member_roles)
        if member.id in self.autist_list:
            member_roles = [discord.utils.get(member.server.roles, id='298782505073377280')]
            if member_roles:
                await self.replace_roles(member, *member_roles)
        if member.id in self.weeb_list:
            member_roles = [discord.utils.get(member.server.roles, id='298782445099024386')]
            if member_roles:
                await self.replace_roles(member, *member_roles)
                
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            try:
                if [role for role in before.roles if role.id  in ["260520774388023297"]] and not [role for role in after.roles if role.id  in ["260520774388023297"]]:
                    member_roles = [discord.utils.get(member.server.roles, id='260520774388023297')]
                    if member_roles:
                        await self.replace_roles(member, *member_roles)
                if [role for role in before.roles if role.id  in ["298781003051302912"]] and not [role for role in after.roles if role.id  in ["298781003051302912"]]:
                    member_roles = [discord.utils.get(member.server.roles, id='298781003051302912')]
                    if member_roles:
                        await self.replace_roles(member, *member_roles)
                if not [role for role in before.roles if role.id  in ["298782505073377280"]] and [role for role in after.roles if role.id  in ["298782505073377280"]]:
                    self.autist_list.append(before.id)
                    print('user {} now autism listed'.format(before.name))
                    write_json('autism.json', self.autist_list)
                if [role for role in before.roles if role.id  in ["298782505073377280"]] and not [role for role in after.roles if role.id  in ["298782505073377280"]]:
                    self.autist_list.remove(before.id)
                    print('user {} now not autistic'.format(before.name))
                    write_json('autism.json', self.autist_list)
                if not [role for role in before.roles if role.id  in ["298782445099024386"]] and [role for role in after.roles if role.id  in ["298782445099024386"]]:
                    self.weeb_list.append(before.id)
                    print('user {} now weeb listed'.format(before.name))
                    write_json('weeb.json', self.weeb_list)
                if [role for role in before.roles if role.id  in ["298782445099024386"]] and not [role for role in after.roles if role.id  in ["298782445099024386"]]:
                    self.weeb_list.remove(before.id)
                    print('user {} now not a weeb'.format(before.name))
                    write_json('weeb.json', self.weeb_list)
            except:
                pass

    async def on_message(self, message):
        if message.author == self.user:
            return
        
        if message.channel.is_private:
            print('pm')
            return

        message_content = message.content.strip()
        
        for item in message.content.strip().split():
            try:
                if 'discord.gg' in item:
                    invite = await self.get_invite(item)
                    if invite.server.id not in self.server_whitelist:
                        if not [role for role in message.author.roles if role.id  in ["298781054909546497", "298781131925487617", '298780936823373824', '298781148752904193']]:
                            await self.safe_delete_message(message)
                            print('detected illegal invite from {}:{}\t{}'.format(message.author.name, message.author.id, item))
                            await self.safe_send_message(message.author, content='I\'ve deleted your message in {} since I detected an invite url in your message! Don\'t advertise servers in Rhinos Place'.format(message.channel.mention))
                            await self.safe_send_message(discord.Object(id='298881243389624321'), content='```\nAction: Message Deletion\nUser(s):{}#{} ({})\nReason:Sent a nonwhitelisted invite url ({} : {})```\nMessage sent in {}: `{}`\n'.format(message.author.name, message.author.discriminator ,message.author.id, item, invite.server.id, message.channel.mention, message.clean_content))
                            return
            except:
                pass
                
        if not message_content.startswith(self.prefix):
            return
        if [role for role in message.author.roles if role.id in ['298782505073377280', '298782445099024386']]:
            return
        try:
            command, *args = shlex.split(message.content.strip())
        except:
            command, *args = message.content.strip().split()
        command = command[len(self.prefix):].lower().strip()
        
        
        handler = getattr(self, 'cmd_%s' % command, None)
        if not handler:
            return

        print("[Command] {0.id}/{0.name} ({1})".format(message.author, message_content))

        argspec = inspect.signature(handler)
        params = argspec.parameters.copy()

        # noinspection PyBroadException
        try:
            handler_kwargs = {}
            if params.pop('message', None):
                handler_kwargs['message'] = message

            if params.pop('channel', None):
                handler_kwargs['channel'] = message.channel

            if params.pop('author', None):
                handler_kwargs['author'] = message.author

            if params.pop('server', None):
                handler_kwargs['server'] = message.server

            if params.pop('mentions', None):
                handler_kwargs['mentions'] = message.mentions

            if params.pop('leftover_args', None):
                            handler_kwargs['leftover_args'] = args
                            
            args_expected = []
            for key, param in list(params.items()):
                doc_key = '[%s=%s]' % (key, param.default) if param.default is not inspect.Parameter.empty else key
                args_expected.append(doc_key)

                if not args and param.default is not inspect.Parameter.empty:
                    params.pop(key)
                    continue

                if args:
                    arg_value = args.pop(0)
                    if arg_value.startswith('<@') or arg_value.startswith('<#'):
                        pass
                    else:
                        handler_kwargs[key] = arg_value
                        params.pop(key)

            if params:
                docs = getattr(handler, '__doc__', None)
                if not docs:
                    docs = 'Usage: {}{} {}'.format(
                        self.prefix,
                        command,
                        ' '.join(args_expected)
                    )

                docs = '\n'.join(l.strip() for l in docs.split('\n'))
                await self.safe_send_message(
                    message.channel,
                    content= '```\n%s\n```' % docs.format(command_prefix=self.prefix),
                             expire_in=15
                )
                return

            response = await handler(**handler_kwargs)
            if response and isinstance(response, Response):
                content = response.content
                if response.reply:
                    content = '%s, %s' % (message.author.mention, content)
                    
                if response.delete_after > 0:
                    await self.safe_delete_message(message)
                    sentmsg = await self.safe_send_message(message.channel, content=content, expire_in=response.delete_after)
                else:
                    sentmsg = await self.safe_send_message(message.channel, content=content)
                    
        except CommandError as e:
            await self.safe_send_message(message.channel, content='```\n%s\n```' % e.message, expire_in=15)

        except:
            await self.safe_send_message(message.channel, content='```\n%s\n```' % traceback.format_exc(), expire_in=60)
            traceback.print_exc()


if __name__ == '__main__':
    bot = RhinoBot()
    bot.run()
