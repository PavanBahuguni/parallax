Skip to main content
Logo for Engineering Hackathon Portal
Search Hackathon XII





P
campaign-home-link
HOME
Projects
Hackers
FAQS
Current phase
Forming Teams
Time left
6
days
Morpheus: The Nutanix MCP Store(D2834)

R
Rupal Sharma

Team Members
R
Rupal Sharma
Description
Morpheus is a unified platform that instantly "MCP-ifies" any Nutanix application or service. It auto-generates Model Context Protocol (MCP) servers from existing Swagger APIs and publishes them to a centralized Internal Playstore. This creates a reusable ecosystem where AI agents can discover and orchestrate tools across our entire stack—eliminating redundant work and standardizing how AI talks to our software.

 The Problem

Siloed AI Integration: Connecting LLMs to our internal products (from Core to Cloud) currently requires writing custom "glue code" for every single API.

Redundant Effort: Multiple teams (e.g., Panacea, NAI, Engineering) often build the same MCP tools for the same services (like Jira, Github, or Prism), leading to wasted cycles and drift.

Maintenance Nightmares: When an API changes, every hard-coded AI tool breaks. There is no single source of truth or governance for AI capabilities across the company.

The Solution

We propose a two-part platform that turns our APIs into AI-ready building blocks:

1. The Generator (Morpheus Core)

Input: Ingests any standard Swagger/OpenAPI specification from a Nutanix service.

Process: Automatically maps API endpoints to MCP tool definitions (e.g., POST /vm becomes create_vm tool).

Output: Spins up a fully deployable, secure MCP server container in minutes.

2. The Playstore (The Marketplace)

Discoverability: A central catalog where generated MCP servers are registered. Developers and agents can search for "Prism MCP", "Unified Storage MCP", or "Collector MCP" and install them with one click.

Reusability: Instead of regenerating the same tools, a team simply subscribes to the existing, verified MCP server from the store.

Governance: Acts as a gatekeeper, ensuring all AI tools respect User RBAC and security policies before they are published.

Team Captain's primary location*
India
Would you like your project to be private?
No
Do you have an open JIRA ticket for this idea? If yes, please provide below. If no, please create and provide below.*
NA
Please describe the technologies being used in your project.
No answer
Expertise Needed
MCP
python
UI
Attachments (0)
No attachments
Requests to join team
Request to Join Team
Category
Surprise Me
Status
Recruiting Team Members
Brightidea Logo