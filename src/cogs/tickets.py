"""
Cog for handling tickets.
"""

import logging
import aiosqlite
import discord
from discord import app_commands
from discord.app_commands import Choice

from cog import Cog
from constants import (
    DATABASE,
    TICKET_SUBMITTED_MSG,
    TicketType
)
from ui import ReportModal, SuggestionModal
from utils import get_member


log = logging.getLogger(__name__)


class Tickets(Cog):
    """
    Cog for handling tickets.
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.group.guild_ids = (bot.main_guild.id,)

    # Ticket command group.
    group = app_commands.Group(
        name='ticket',
        description='Open tickets here...'
    )

    async def create_ticket_channel(
        self, prefix:str, ticket_id:int
        ) -> discord.TextChannel:
        """
        Creates and returns a discord TextChannel object to store a
        new ticket.
        """
        
        log.debug(f'Creating new ticket channel for ticket #{ticket_id}')

        # The guild and category where the new channel will be created
        guild: discord.Guild = self.bot.main_guild
        category: discord.CategoryChannel = discord.Object(
            id=self.bot.config['guild']['category_ids']['tickets']
        )

        # Return the newly created ticket channel
        return await guild.create_text_channel(
            name=f"{prefix}-ticket-{ticket_id}",
            category=category
        )
    
    def create_ticket_embed(
        self, ticket_type:TicketType, ticket_id:int, *args
        ):
        """
        Creates and returns a discord Embed for use in tickets.
        """

        log.debug(f'Creating new ticket embed for ticket #{ticket_id}')

        # The embed that will be returned
        embed = discord.Embed(
            colour=args[0].colour,
            title=f"{ticket_type.name.title()} Ticket #{ticket_id}",
        )
        
        # Add the ticket details to the embed via fields
        if ticket_type == ticket_type.REPORT:
            embed.add_field(name="Accuser", value=args[0].mention, inline=False)
            embed.add_field(name="Accusing", value=args[1].mention, inline=False)
            embed.add_field(name="Reason Given", value=args[2], inline=False)
        else:
            embed.add_field(name="Suggestion From", value=args[0].mention, inline=False)
            embed.add_field(name="Suggestion/Feature Request", value=args[1], inline=False)

        return embed

    async def create_ticket(
        self,
        interaction:discord.Interaction,
        ticket_type:TicketType,
        *args
        ):
        """
        Create a new ticket. This will create a new channel and
        embed for the ticket.
        """
        
        log.debug(f'Creating new ticket of type {ticket_type.name}')

        # Show that the bot is thinking to prevent the interaction timing out
        # await interaction.response.defer(ephemeral=True)

        # Shorthands for replying to the user
        followup = interaction.followup.send

        # This sql query will get the next ticket id
        get_id_sql = "SELECT ticket_id FROM {0} ORDER BY ticket_id " \
                     "DESC LIMIT 1"

        # Normalize the data to be inserted into the database
        normalized_sql_values = []
        for arg in args:
            
            # If the arg is a discord.Member object, get the id instead
            if isinstance(arg, discord.Member):
                normalized_sql_values.append(arg.id)
                continue

            # Otherwise just append the value
            normalized_sql_values.append(arg)

        # Determine what sql query to use based on the ticket type
        if ticket_type == TicketType.REPORT:
            
            # Prevent troll users from creating tickets that report themselves
            if args[1] == interaction.user:
                await followup(
                    'You cannot report yourself\n  ╰(ಠ ͟ʖ ಠ)╯',
                    ephemeral=True
                )
                return

            table = 'user_report_tickets'
            values = '(user_id, accused_user_id, channel_id, reason_msg) VALUES (?, ?, NULL, ?)'

        elif ticket_type == TicketType.SUGGESTION:
            table = 'user_suggestion_tickets'
            values = '(user_id, channel_id, suggestion_msg) VALUES (?, NULL, ?)'


        ticket_query = f'INSERT INTO {table} {values}'
        get_id_sql = get_id_sql.format(table)

        log.debug('Creating new ticket in database')

        # Write the ticket to the database
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(ticket_query, normalized_sql_values)
            await db.commit()
            
            # Get the ticket id of the newly created ticket
            ticket_id = await db.execute_fetchall(get_id_sql)
            ticket_id = ticket_id[0][0]  # get value from [(int,)])
        
        log.debug(f'Ticket created in database with id: {ticket_id}')

        # Create a channel for the new ticket to be discussed in
        channel = await self.create_ticket_channel(
            prefix=ticket_type.name.lower(),
            ticket_id=ticket_id
        )

        # Store the channel id in the database with the ticket
        channel_query = f"UPDATE {table} SET channel_id = ? WHERE ticket_id = ?"
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(channel_query, (channel.id, ticket_id))
            await db.commit()

        # Create an embed for the ticket
        embed = self.create_ticket_embed(
            ticket_type,
            ticket_id,
            *args
        )
        await channel.send(embed=embed)

    @group.command(name='suggestion')
    async def create_suggestion_ticket(self, interaction:discord.Interaction):
        """
        Suggest a feature for the server
        """

        async def on_submit(modal_interaction, suggestion):
            """
            Called when the user submits the suggestion modal
            """

            # Create a ticket based of the user suggestion
            await self.create_ticket(
                interaction, TicketType.SUGGESTION,
                interaction.user,
                suggestion
            )

            # Thank the user for their suggestion!
            await modal_interaction.response.send_message(
                'Thanks for your suggestion! \
                \nWe will look into it as soon as possible.',
                ephemeral=True
            )

        # Create a modal for the user to submit their suggestion
        await interaction.response.send_modal(SuggestionModal(on_submit))

    @group.command(name='report')
    async def create_report_ticket(self, interaction: discord.Interaction):
        """
        Report a user for misbehaviour or bullying
        """
        async def on_submit(modal_interaction, accused_user, reason):
            """
            Called when the user submits the report modal
            """

            # Get a discord.Member object based of the passed accused name or id
            member = await get_member(modal_interaction, accused_user)
            
            # If the member is not found, cancel this ticket.
            if not isinstance(member, discord.Member):
                await modal_interaction.response.send_message(
                    'Unable to process your report. \
                    \nPlease make sure you are entering a valid username.',
                    ephemeral=True
                )
                return

            # Create a ticket using the information provided
            await self.create_ticket(
                interaction, TicketType.REPORT,
                interaction.user,
                member,
                reason
            )

            # Thank the user for their report!
            await modal_interaction.response.send_message(
                'Thanks for your report! \
                \nWe will look into it as soon as possible.',
                ephemeral=True
            )

        # Create a modal for the user to send their report
        await interaction.response.send_modal(ReportModal(on_submit))

    
    @group.command(name='close')
    @app_commands.describe(
        ticket_type='The type of ticket you are closing',
        ticket_id='The ID of the ticket you are closing'
    )
    @app_commands.choices(ticket_type=[
        Choice(name='report ticket', value=TicketType.REPORT.value),
        Choice(name='suggestion ticket', value=TicketType.SUGGESTION.value)
    ])
    # @app_commands.checks.has_any_role(ADMIN_ROLE_ID)
    async def close_ticket(
        self,
        interaction:discord.Interaction,
        ticket_type:TicketType,
        ticket_id:int
    ):
        """
        Close a ticket (admin/mod only)
        """

        # Shorthand for replying to the user
        send = interaction.response.send_message

        # Find the correct table to use based on the ticket type
        if ticket_type == TicketType.REPORT:
            table = 'user_report_tickets'
        elif ticket_type == TicketType.SUGGESTION:
            table = 'user_suggestion_tickets'
        else:
            raise ValueError('Invalid ticket type')  # This should never happen

        query = f'FROM {table} WHERE ticket_id=?'

        # Check that the ticket exists
        async with aiosqlite.connect(DATABASE) as db:
            try:
                result = await db.execute_fetchall(
                    'SELECT channel_id ' + query,
                    (ticket_id,)
                )
                channel_id = result[0][0]  # raises IndexError if ticket doesn't exist
            except IndexError:
                await send(
                    f'There are no {ticket_type.name.lower()} ' \
                    f'tickets with the id: {ticket_id}',
                    ephemeral=True
                )
                return

        # Delete the ticket from the database
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute('DELETE ' + query,(ticket_id,))
            await db.commit()

        # Delete the ticket channel
        guild: discord.Guild = self.bot.main_guild
        await guild.get_channel(channel_id).delete(reason='Ticket closed')

        await send(
            'Ticket closed. The ticket channel has also been deleted.',
            ephemeral=True
        )


async def setup(bot):
    """
    Setup function.
    Required for all cog files.
    Used by the bot to load this cog.
    """

    cog = Tickets(bot)
    await bot.add_cog(cog, guilds=(bot.main_guild,))
