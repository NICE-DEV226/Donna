# PubSub Extension

This project is a Pub/Sub service extension, designed to provide a unified interface for message publishing and streaming. It is built as part of the `auth` extensions and integrates with the `xcore` services framework.

## Project Overview

The PubSub extension allows for asynchronous message distribution across different channels. It supports multiple backend providers and utilizes `xcore` extensions for configuration and service management.

### Main Technologies
- **Python**: Core programming language.
- **Pydantic**: Used for robust configuration validation.
- **Redis (asyncio)**: Primary backend with connection pooling.
- **MQTT (gmqtt)**: HiveMQ provider for IoT/M2M messaging.
- **xcore**: Service framework integration.

## Architecture

The project follows a provider-based architecture with a common interface:

- **`service.py`**: The entry point for the extension. It manages the lifecycle of the selected provider and provides high-level Pub/Sub methods.
- **`provider/`**:
    - `base.py`: Defines the `PubSubProvider` abstract base class.
    - `redis.py`: Improved Redis implementation with connection pooling.
    - `hyvemq.py`: MQTT implementation for HiveMQ.
    - `memory.py`: In-memory provider for testing.
    - `section.py`: Pydantic models for configuration.

## Providers

| Provider | Purpose | Dependencies |
| :--- | :--- | :--- |
| **Redis** | Scalable production pub/sub | `redis` |
| **HiveMQ** | MQTT based messaging | `gmqtt` |
| **Memory** | Local development and testing | None |

## Building and Running

### Prerequisites
- Python 3.10+
- `redis` and `pydantic` libraries.
- `gmqtt` (optional, for HiveMQ).

### Key Commands
- **Testing**: Use the `memory` provider for unit tests to avoid external dependencies.
- **Configuration**: Use the `PubSubConf` model to define your settings in `xcore.yaml`.

## Development Conventions

- **Validation**: Always use Pydantic models for configuration.
- **Provider Interface**: New providers must inherit from `PubSubProvider` and implement `connect`, `close`, `publish`, and `stream`.
- **Async First**: All operations are asynchronous.
