import json
from argparse import ArgumentParser


def hello_world(name=None):
    if name:
        return f"Hello {name}!"
    return "Hello World!"


def hello_world_blocks():
    return json.dumps(
        [{"type": "section", "text": {"type": "plain_text", "text": "Hello World!"}}]
    )


def hello_world_blocks_error():
    raise Exception("An error was found!")


def parse_args():
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="subparser_name")
    h1 = subparsers.add_parser("hello_world")
    h1.add_argument("--name")
    h1.set_defaults(function=hello_world)
    h2 = subparsers.add_parser("hello_world_blocks")
    h2.set_defaults(function=hello_world_blocks)
    h3 = subparsers.add_parser("hello_world_blocks_error")
    h3.set_defaults(function=hello_world_blocks_error)
    h4 = subparsers.add_parser("hello_world_no_output")
    h4.set_defaults(function=hello_world)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.subparser_name == "hello_world":
        print(args.function(args.name))
    elif args.subparser_name == "hello_world_no_output":
        args.function()
    else:
        print(args.function())


if __name__ == "__main__":
    main()
