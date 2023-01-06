import sys
import logging
import argparse
import environs

from my_github.db_session import create_session
from my_github.models import GitHubEvent, EventSourceEnum
from my_github.github_api import GitHubAPI, datetime_from_github_time

env = environs.Env()
env.read_env(recurse=False)


DEBUG = env.bool('DEBUG', False)

session = create_session(
    env.str('DB_URL'),
    use_ssl=env.bool('DB_USE_SSL', True),
    ssl_ca_path=env.str('DB_SSL_CA_PATH', '/etc/ssl/cert.pem'),
)
api = GitHubAPI(env.str('MY_GITHUB_USERNAME'), env.str('MY_GITHUB_TOKEN'))


def save_github_events(event_source, raw_events):
    if not raw_events:
        return
    logging.debug(f'saving github events, count: { len(raw_events) }')
    for e in raw_events:
        session.merge(GitHubEvent(
            id=e['id'],
            event_type=e['type'],
            actor_id=e['actor']['id'],
            actor_login=e['actor']['login'],
            repo_id=e['repo']['id'],
            repo_name=e['repo']['name'],
            payload=e['payload'],
            public=e['public'],
            org_id=e['org']['id'] if 'org' in e else None,
            org_login=e['org']['login'] if 'org' in e else None,
            created_at=e['created_at'],
            event_source=event_source,
        ))
    session.commit()


def _sync_github_events(event_source, github_api_method):
    oldest_event = session.query(GitHubEvent).where(
        GitHubEvent.event_source == event_source).order_by(GitHubEvent.created_at.asc()).first()
    logging.debug(f'Oldest event: { oldest_event.created_at if oldest_event else None }')

    page = 1

    if not oldest_event:
        logging.info('No events in the database(should be first call), start to fetch all events...')
        while True:
            raw_events = github_api_method(page=page)
            if not raw_events:
                break
            save_github_events(event_source, raw_events)
            page += 1
        return

    while True:
        latest_event = session.query(GitHubEvent).order_by(GitHubEvent.created_at.desc()).first()
        raw_events = github_api_method(page=1)
        if not raw_events:
            # No more events
            break

        if latest_event.created_at < datetime_from_github_time(raw_events[0]['created_at']):
            save_github_events(event_source, raw_events)

        if latest_event.created_at < datetime_from_github_time(raw_events[-1]['created_at']):
            # There are more events
            page += 1
        else:
            logging.debug(f'there are no more events, latest_event: { latest_event.created_at }')
            break
    logging.info(f'🎉 Syncing events ({ event_source }) done! 🎉')


def sync_user_created_events():
    logging.info('🚀 Syncing user created events...')
    _sync_github_events(
        EventSourceEnum.USER_CREATED.value,
        api.get_authenticated_user_created_events,
    )


def sync_user_received_events():
    logging.info('🚀 Syncing user received events...')
    _sync_github_events(
        EventSourceEnum.USER_RECEIVED.value,
        api.get_authenticated_user_received_events,
    )


def main():
    logging.basicConfig(
        level=logging.DEBUG if DEBUG else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(prog='my_github events sync tools')
    parser.add_argument('--sync-user-created-events', action='store_true')
    parser.add_argument('--sync-user-received-events', action='store_true')
    args = parser.parse_args(args=None if sys.argv[1:] else ['--help'])
    args = parser.parse_args()

    if args.sync_user_created_events:
        sync_user_created_events()

    if args.sync_user_received_events:
        sync_user_received_events()

if __name__ == '__main__':
    main()
        