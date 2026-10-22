# Isolated JARVIS test project

Three Python modules and their unit tests. Pricing contains an intentional defect. All tests must execute only inside a Docker container with no network, no capabilities, a read-only source mount, and limited resources. The trusted host orchestrator never imports or runs the fixture on Windows.
