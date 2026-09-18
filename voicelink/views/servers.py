"""MIT License

Copyright (c) 2023 - present Vocard Development

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import math
import discord
from discord.ext import commands
from typing import TYPE_CHECKING

from ..config import Config
from ..utils import truncate_string, format_ms
from .utils import BaseModal

if TYPE_CHECKING:
    import voicelink


class GuildSelect(discord.ui.Select):
    def __init__(self, view: ServersView, guilds: list[discord.Guild]):
        self.servers_view = view
        options = []
        for guild in guilds:
            label = truncate_string(guild.name, 100)
            status_text = "Idle"
            if vc := guild.voice_client:
                if hasattr(vc, "is_playing") and vc.is_playing:
                    status_text = "Playing"
                elif hasattr(vc, "is_paused") and vc.is_paused:
                    status_text = "Paused"
                else:
                    status_text = "In Voice"

            desc = f"ID: {guild.id} • {guild.member_count or 0} members • {status_text}"
            desc = truncate_string(desc, 100)
            options.append(discord.SelectOption(label=label, value=str(guild.id), description=desc))

        if not options:
            options = [discord.SelectOption(label="No servers available", value="none")]

        super().__init__(
            placeholder="Select a server to inspect or manage...",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "none":
            return await interaction.response.defer()

        guild_id = int(self.values[0])
        guild = self.servers_view.bot.get_guild(guild_id)
        if not guild:
            return await interaction.response.send_message("Server not found or bot is no longer in it.", ephemeral=True)

        self.servers_view.selected_guild = guild
        self.servers_view.update_components()
        await interaction.response.edit_message(
            embed=self.servers_view.build_detail_embed(guild),
            view=self.servers_view
        )


class ServersView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        author: discord.User | discord.Member,
        timeout: float | None = 300
    ) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author = author
        self.message: discord.Message | discord.WebhookMessage | None = None
        self.page: int = 0
        self.per_page: int = 6
        self.selected_guild: discord.Guild | None = None

        self.update_components()

    @property
    def sorted_guilds(self) -> list[discord.Guild]:
        return sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(len(self.bot.guilds) / self.per_page))

    def get_current_page_guilds(self) -> list[discord.Guild]:
        guilds = self.sorted_guilds
        start = self.page * self.per_page
        end = start + self.per_page
        return guilds[start:end]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in Config().bot_access_user or await self.bot.is_owner(interaction.user):
            return True
        await interaction.response.send_message("You do not have permission to use this panel.", ephemeral=True)
        return False

    def update_components(self) -> None:
        self.clear_items()

        if self.selected_guild:
            # Details view buttons
            back_btn = discord.ui.Button(label="Server List", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
            back_btn.callback = self.back_to_list
            self.add_item(back_btn)

            invite_btn = discord.ui.Button(label="Create Invite", emoji="🔗", style=discord.ButtonStyle.primary, row=1)
            invite_btn.callback = self.create_invite
            self.add_item(invite_btn)

            leave_btn = discord.ui.Button(label="Leave Server", emoji="🚪", style=discord.ButtonStyle.danger, row=1)
            leave_btn.callback = self.confirm_leave
            self.add_item(leave_btn)
        else:
            # Overview view items: Select menu + pagination controls
            page_guilds = self.get_current_page_guilds()
            self.add_item(GuildSelect(self, page_guilds))

            fast_back = discord.ui.Button(emoji="⏮️", disabled=self.page <= 0, row=1)
            fast_back.callback = self.first_page
            self.add_item(fast_back)

            prev_btn = discord.ui.Button(emoji="◀️", disabled=self.page <= 0, row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            page_label = discord.ui.Button(
                label=f"{self.page + 1}/{self.total_pages}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=1
            )
            self.add_item(page_label)

            next_btn = discord.ui.Button(emoji="▶️", disabled=self.page >= self.total_pages - 1, row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)

            fast_next = discord.ui.Button(emoji="⏭️", disabled=self.page >= self.total_pages - 1, row=1)
            fast_next.callback = self.last_page
            self.add_item(fast_next)

            refresh_btn = discord.ui.Button(emoji="🔄", style=discord.ButtonStyle.secondary, row=2)
            refresh_btn.callback = self.refresh_view
            self.add_item(refresh_btn)

    def build_overview_embed(self) -> discord.Embed:
        guilds = self.sorted_guilds
        total_servers = len(guilds)
        total_members = sum(g.member_count or 0 for g in guilds)
        total_players = len(self.bot.voice_clients)

        embed = discord.Embed(
            title="🌐 Bot Server Management",
            description=(
                f"```== Server Statistics ==\n"
                f"• Total Servers:  {total_servers}\n"
                f"• Total Reach:    {total_members:,} members\n"
                f"• Active Players: {total_players} connected```"
            ),
            color=Config().embed_color
        )

        page_guilds = self.get_current_page_guilds()
        if not page_guilds:
            embed.add_field(name="No Servers", value="The bot is currently not in any servers.", inline=False)
        else:
            for idx, guild in enumerate(page_guilds, start=self.page * self.per_page + 1):
                status_icon = "⚪"
                playing_info = "Not connected"
                if vc := guild.voice_client:
                    if hasattr(vc, "is_playing") and vc.is_playing:
                        status_icon = "🟢"
                        track = getattr(vc, "current", None)
                        playing_info = f"Playing: **{truncate_string(track.title, 35)}**" if track else "Playing"
                    elif hasattr(vc, "is_paused") and vc.is_paused:
                        status_icon = "🟡"
                        track = getattr(vc, "current", None)
                        playing_info = f"Paused: **{truncate_string(track.title, 35)}**" if track else "Paused"
                    else:
                        status_icon = "🔊"
                        playing_info = "Connected (idle)"

                owner = guild.owner
                owner_str = f"{owner.name}" if owner else f"ID: {guild.owner_id}"

                embed.add_field(
                    name=f"{idx}. {guild.name}",
                    value=(
                        f"• **ID**: `{guild.id}`\n"
                        f"• **Members**: `{guild.member_count or 0}`\n"
                        f"• **Owner**: {owner_str}\n"
                        f"• **Voice**: {status_icon} {playing_info}"
                    ),
                    inline=False
                )

        embed.set_footer(text=f"Page {self.page + 1} of {self.total_pages} • Select a server below to inspect")
        return embed

    def build_detail_embed(self, guild: discord.Guild) -> discord.Embed:
        embed = discord.Embed(
            title=f"🔎 Server Details: {guild.name}",
            color=Config().embed_color
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        owner = guild.owner
        owner_display = f"<@{guild.owner_id}> (`{owner.name}`)" if owner else f"<@{guild.owner_id}>"

        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        stage_channels = len(guild.stage_channels)
        categories = len(guild.categories)

        created_ts = int(guild.created_at.timestamp())
        joined_ts = int(guild.me.joined_at.timestamp()) if guild.me and guild.me.joined_at else None
        joined_display = f"<t:{joined_ts}:F> (<t:{joined_ts}:R>)" if joined_ts else "Unknown"

        embed.add_field(
            name="📋 General Information",
            value=(
                f"• **ID**: `{guild.id}`\n"
                f"• **Owner**: {owner_display}\n"
                f"• **Created**: <t:{created_ts}:F> (<t:{created_ts}:R>)\n"
                f"• **Bot Joined**: {joined_display}\n"
                f"• **Members**: `{guild.member_count or 0}`\n"
                f"• **Roles**: `{len(guild.roles)}` | **Emojis**: `{len(guild.emojis)}`\n"
                f"• **Boosts**: Level {guild.premium_tier} ({guild.premium_subscription_count} boosts)"
            ),
            inline=False
        )

        embed.add_field(
            name="📁 Channels Breakdown",
            value=(
                f"• Text: `{text_channels}` | Voice: `{voice_channels}`\n"
                f"• Stages: `{stage_channels}` | Categories: `{categories}`"
            ),
            inline=False
        )

        # Voice status
        vc = guild.voice_client
        if vc and hasattr(vc, "channel") and vc.channel:
            channel_name = vc.channel.name
            track = getattr(vc, "current", None)
            if track:
                pos = getattr(vc, "position", 0)
                dur = track.formatted_length if hasattr(track, "formatted_length") else format_ms(track.length)
                player_status = (
                    f"• **Channel**: `{channel_name}`\n"
                    f"• **Status**: {'⏸️ Paused' if getattr(vc, 'is_paused', False) else '▶️ Playing'}\n"
                    f"• **Track**: [{truncate_string(track.title, 40)}]({track.uri})\n"
                    f"• **Position**: `[{format_ms(pos)}/{dur}]`\n"
                    f"• **Requester**: {track.requester.mention if hasattr(track, 'requester') and track.requester else 'Unknown'}\n"
                    f"• **Volume**: `{getattr(vc, 'volume', 100)}%` | **Queue**: `{getattr(vc.queue, 'count', 0)} tracks`"
                )
            else:
                player_status = f"• **Channel**: `{channel_name}`\n• **Status**: 🔊 Connected (no track playing)"
        else:
            player_status = "• *The bot is not currently connected to a voice channel in this server.*"

        embed.add_field(name="🎵 Audio Player Status", value=player_status, inline=False)

        # Bot permissions
        if guild.me:
            perms = guild.me.guild_permissions
            key_perms = []
            if perms.administrator:
                key_perms.append("Administrator")
            else:
                if perms.manage_guild:
                    key_perms.append("Manage Server")
                if perms.manage_channels:
                    key_perms.append("Manage Channels")
                if perms.send_messages:
                    key_perms.append("Send Messages")
                if perms.connect:
                    key_perms.append("Connect")
                if perms.speak:
                    key_perms.append("Speak")
                if perms.create_instant_invite:
                    key_perms.append("Create Invite")

            embed.add_field(name="🛡️ Bot Permissions", value=", ".join(key_perms) if key_perms else "Standard", inline=False)

        embed.set_footer(text=f"Server ID: {guild.id} • Use action buttons below")
        return embed

    async def first_page(self, interaction: discord.Interaction) -> None:
        self.page = 0
        self.update_components()
        await interaction.response.edit_message(embed=self.build_overview_embed(), view=self)

    async def prev_page(self, interaction: discord.Interaction) -> None:
        if self.page > 0:
            self.page -= 1
        self.update_components()
        await interaction.response.edit_message(embed=self.build_overview_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction) -> None:
        if self.page < self.total_pages - 1:
            self.page += 1
        self.update_components()
        await interaction.response.edit_message(embed=self.build_overview_embed(), view=self)

    async def last_page(self, interaction: discord.Interaction) -> None:
        self.page = self.total_pages - 1
        self.update_components()
        await interaction.response.edit_message(embed=self.build_overview_embed(), view=self)

    async def refresh_view(self, interaction: discord.Interaction) -> None:
        self.selected_guild = None
        self.page = min(self.page, self.total_pages - 1)
        self.update_components()
        await interaction.response.edit_message(embed=self.build_overview_embed(), view=self)

    async def back_to_list(self, interaction: discord.Interaction) -> None:
        self.selected_guild = None
        self.update_components()
        await interaction.response.edit_message(embed=self.build_overview_embed(), view=self)

    async def create_invite(self, interaction: discord.Interaction) -> None:
        if not self.selected_guild:
            return await interaction.response.send_message("No server selected.", ephemeral=True)

        guild = self.selected_guild
        # Find a suitable text channel where bot can create invite
        invite = None
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).create_instant_invite:
                try:
                    invite = await channel.create_invite(max_age=3600, max_uses=1, reason="Owner requested invite via Vocard Server Inspector")
                    break
                except Exception:
                    continue

        if not invite:
            for channel in guild.voice_channels:
                if channel.permissions_for(guild.me).create_instant_invite:
                    try:
                        invite = await channel.create_invite(max_age=3600, max_uses=1, reason="Owner requested invite via Vocard Server Inspector")
                        break
                    except Exception:
                        continue

        if invite:
            await interaction.response.send_message(f"🔗 Generated temporary invite for **{guild.name}**:\n{invite.url}", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Bot lacks `Create Instant Invite` permission in **{guild.name}** channels.", ephemeral=True)

    async def confirm_leave(self, interaction: discord.Interaction) -> None:
        if not self.selected_guild:
            return await interaction.response.send_message("No server selected.", ephemeral=True)

        guild = self.selected_guild
        modal = BaseModal(
            title=f"Leave {truncate_string(guild.name, 35)}?",
            custom_id="confirm_leave_modal",
            items=[
                discord.ui.TextInput(
                    label="Confirmation",
                    placeholder=f'Type "CONFIRM" to make the bot leave {guild.name}',
                    custom_id="confirm_text",
                    required=True
                )
            ]
        )
        await interaction.response.send_modal(modal)
        await modal.wait()

        if modal.values.get("confirm_text", "").strip() != "CONFIRM":
            return await interaction.followup.send("Action cancelled. You must type `CONFIRM` to leave.", ephemeral=True)

        try:
            guild_name = guild.name
            await guild.leave()
            self.selected_guild = None
            self.page = min(self.page, max(0, self.total_pages - 1))
            self.update_components()
            await interaction.followup.send(f"✅ Successfully left **{guild_name}**.", ephemeral=True)
            if self.message:
                await self.message.edit(embed=self.build_overview_embed(), view=self)
        except Exception as e:
            await interaction.followup.send(f"Failed to leave server: {e}", ephemeral=True)
