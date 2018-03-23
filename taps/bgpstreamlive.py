import sys
import os
import argparse
import grpc
import time
from netaddr import IPNetwork, IPAddress
# install as described in https://bgpstream.caida.org/docs/install/pybgpstream
from _pybgpstream import BGPStream, BGPRecord, BGPElem

# to import protogrpc, since the root package has '-'
# in the name ("artemis-tool")
this_script_path = os.path.realpath(__file__)
upper_dir = '/'.join(this_script_path.split('/')[:-2])
sys.path.insert(0, upper_dir)
from protogrpc import service_pb2, service_pb2_grpc

START_TIME_OFFSET = 3600 # seconds


def as_mapper(asn_str):
    if asn_str != '':
        return int(asn_str)
    return 0

def run_bgpstream(prefixes=[], projects=[], start=0, end=0):
    """
    Retrieve all records related to a list of prefixes
    https://bgpstream.caida.org/docs/api/pybgpstream/_pybgpstream.html

    :param prefix: <str> input prefix
    :param start: <int> start timestamp in UNIX epochs
    :param end: <int> end timestamp in UNIX epochs (if 0 --> "live mode")

    :return: -
    """
    channel = grpc.insecure_channel('localhost:50051')
    stub = service_pb2_grpc.MessageListenerStub(channel)

    # create a new bgpstream instance and a reusable bgprecord instance
    stream = BGPStream()
    rec = BGPRecord()

    # consider collectors from given projects
    for project in projects:
        stream.add_filter('project', project)

    # filter prefixes
    for prefix in prefixes:
        stream.add_filter('prefix', prefix)

    # filter record type
    stream.add_filter('record-type', 'updates')

    # filter based on timing (if end=0 --> live mode)
    stream.add_interval_filter(start, end)

    # set live mode
    stream.set_live_mode()

    # start the stream
    stream.start()

    # print('BGPStream started...')
    # print('Projects ' + str(projects))
    # print('Prefixes ' + str(prefixes))
    # print('Start ' + str(start))
    # print('End ' + str(end))

    # get next record
    while stream.get_next_record(rec):
        if (rec.status != "valid") or (rec.type != "update"):
            continue

        # get next element
        elem = rec.get_next_elem()

        while elem:
            if elem.type in ["A", "W"]:
                this_prefix = str(elem.fields['prefix'])
                service = "bgpstream|{}|{}".format(str(rec.project), str(rec.collector))
                if elem.type == "A":
                    as_path = list(map(as_mapper, elem.fields['as-path'].split(" ")))
                else:
                    as_path = ''

                for prefix in prefixes:
                    if IPAddress(this_prefix.split('/')[0]) in IPNetwork(prefix):
                        stub.queryMformat(service_pb2.MformatMessage(
                            type=str(elem.type),
                            timestamp=float(elem.time),
                            as_path=as_path,
                            service=service,
                            prefix=this_prefix
                        ))

            elem = rec.get_next_elem()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='BGPStream Live Monitor')
    parser.add_argument('-p', '--prefix', type=str, dest='prefix', default=None,
                        help='Prefix to be monitored')
    parser.add_argument('-m', '--mon_projects', type=str, dest='mon_projects', default=None,
                        help='projects to consider for monitoring')

    args = parser.parse_args()

    prefixes = args.prefix.split(',')
    projects = args.mon_projects.split(',')
    run_bgpstream(prefixes, projects, start=int(time.time()) - START_TIME_OFFSET, end=0)

