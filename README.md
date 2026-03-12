# Agent2Aent-Openclaw
Improved Version of OpenClaw: Integration of On-Device Intelligence and Cloud-Based Intelligence

OpenClaw relies on the power of cloud-based LLMs to interact with users through apps like instant messengers, and handles all sorts of sophisticated tasks with its extensive agent functionalities. That said, a string of recent events has laid bare its undeniable security flaws. Even with full configuration options and rigid permission controls in place, this lobster still finds all kinds of unexpected ways to "wipe every file off your computer".

In my view, local permission control shouldn’t be managed by these bare-bones config files. This idea comes from my past work and hands-on robotics experience. A powerful on-device intelligence should handle all local sensing and execution, while the robust cloud-based intelligence is there to guide the relatively less capable on-device system. Think of how modern intelligent robots work: a robot can perceive the world around it and take actions completely on its own. If it’s paired with a cloud-based brain, that brain should tell it where to go and how to approach a task — not directly control every single step it takes. What’s more, the robot has every right to refuse to carry out the cloud brain’s commands, either because it lacks the capability to complete them, or for any other legitimate reason.

That’s why I’ve developed this Agent2Agent OpenClaw solution. It has just one critical difference from the conventional version: we’ve added a dedicated on-device agent. This agent picks up commands from the cloud-based agent, and acts as your dedicated "personal butler" — the only entity with the authority to control your privacy-sensitive local devices.

![github画图](https://github.com/user-attachments/assets/3f08aa23-f102-4ff6-b962-8bff4e620fe5)

For this on-device agent, we’ve opted to deploy a Vision Language Model (VLM) locally, and it only needs to handle simple recognition and basic instruction tasks. 

👏👏The project is now in full swing with intensive development, and feel free to reach out and connect if you’re a fellow "lobster farmer" with interest in this work!

