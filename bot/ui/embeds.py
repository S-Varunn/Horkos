import discord
from datetime import datetime
from typing import List
from db.models import Commitment, CommitmentStatus


def create_commitment_embed(commitment: Commitment, is_alert: bool = False) -> discord.Embed:
    """Creates a visually polished embed for a commitment or upcoming alert."""
    if is_alert:
        color = discord.Color.gold()
        title = "⏰ Commitment Radar Alert"
        desc = f"Hey <@{commitment.user_id}>, you made a promise that is due soon!"
    else:
        color = discord.Color.blurple()
        title = "🎯 Micro-Commitment Registered"
        desc = f"Tracked for <@{commitment.user_id}>"

    embed = discord.Embed(
        title=title,
        description=desc,
        color=color,
        timestamp=datetime.utcnow()
    )

    embed.add_field(name="📋 Task", value=f"**{commitment.task_title}**", inline=False)
    
    if commitment.recipient:
        embed.add_field(name="👤 For / Recipient", value=commitment.recipient, inline=True)
    
    # Format deadline as Discord relative timestamp
    deadline_ts = int(commitment.deadline_utc.timestamp())
    embed.add_field(
        name="⏳ Implied Deadline",
        value=f"<t:{deadline_ts}:R> (<t:{deadline_ts}:t>)",
        inline=True
    )
    
    if commitment.relative_deadline_text:
        embed.add_field(name="💬 Mentioned Timeframe", value=f'"{commitment.relative_deadline_text}"', inline=True)

    status_emojis = {
        CommitmentStatus.PENDING: "🟡 In Progress",
        CommitmentStatus.NOTIFIED: "🟠 Due Soon",
        CommitmentStatus.COMPLETED: "✅ Completed",
        CommitmentStatus.SNOOZED: "⏱️ Postponed",
        CommitmentStatus.CANCELLED: "❌ Cancelled"
    }
    status_str = status_emojis.get(commitment.status, str(commitment.status))
    embed.add_field(name="Status", value=status_str, inline=True)

    if commitment.context_snippet:
        embed.add_field(name="Context", value=commitment.context_snippet[:200], inline=False)

    embed.set_footer(text=f"Commitment Radar ID: #{commitment.id} • Click below to resolve or update")
    return embed


def create_commitments_list_embed(commitments: List[Commitment], user_name: str) -> discord.Embed:
    """Creates an overview embed listing all active commitments for a user."""
    embed = discord.Embed(
        title=f"🎯 Active Commitments for {user_name}",
        description="Here are the micro-commitments detected across your conversations:",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )

    if not commitments:
        embed.description = "🎉 No open micro-commitments! You're completely caught up."
        return embed

    for c in commitments:
        deadline_ts = int(c.deadline_utc.timestamp())
        status_icon = "🟡" if c.status in [CommitmentStatus.PENDING, CommitmentStatus.NOTIFIED] else "✅"
        recipient_info = f" (for {c.recipient})" if c.recipient else ""
        
        embed.add_field(
            name=f"{status_icon} #{c.id}: {c.task_title}{recipient_info}",
            value=f"Due: <t:{deadline_ts}:R> | Originally: *\"{c.raw_text[:60]}...\"*",
            inline=False
        )

    embed.set_footer(text="Use the action buttons or /commitments resolve <id>")
    return embed


def create_resolution_embed(commitment: Commitment, action: str) -> discord.Embed:
    """Creates an embed confirming resolution or postponement."""
    embed = discord.Embed(
        title=f"✅ Commitment Updated: #{commitment.id}",
        description=f"**{commitment.task_title}** has been marked as **{action}**.",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    return embed
