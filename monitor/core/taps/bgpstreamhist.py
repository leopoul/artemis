import argparse
import csv
import glob
import time

import ujson as json
from artemis_utils import get_logger
from artemis_utils import key_generator
from artemis_utils import load_json
from artemis_utils import mformat_validator
from artemis_utils import normalize_msg_path
from artemis_utils import RABBITMQ_URI
from artemis_utils.rabbitmq_util import create_exchange
from kombu import Connection
from kombu import Producer
from netaddr import IPAddress
from netaddr import IPNetwork

log = get_logger()


class BGPStreamHist:
    def __init__(self, prefixes_file=None, input_dir=None):
        self.module_name = "bgpstreamhist|{}".format(input_dir)
        self.prefixes = load_json(prefixes_file)
        assert self.prefixes is not None
        self.input_dir = input_dir
        self.connection = None
        self.update_exchange = None

    def parse_bgpstreamhist_csvs(self):
        with Connection(RABBITMQ_URI) as connection:
            self.update_exchange = create_exchange(
                "bgp-update", connection, declare=True
            )
            producer = Producer(connection)
            validator = mformat_validator()
            for csv_file in glob.glob("{}/*.csv".format(self.input_dir)):
                try:
                    with open(csv_file, "r") as f:
                        csv_reader = csv.reader(f, delimiter="|")
                        for row in csv_reader:
                            try:
                                if len(row) != 9:
                                    continue
                                if row[0].startswith("#"):
                                    continue
                                # example row: 139.91.0.0/16|8522|1403|1403 6461 2603 21320
                                # 5408
                                # 8522|routeviews|route-views2|A|"[{""asn"":1403,""value"":6461}]"|1517446677
                                this_prefix = row[0]
                                if row[6] == "A":
                                    as_path = row[3].split(" ")
                                    communities = json.loads(row[7])
                                else:
                                    as_path = []
                                    communities = []
                                service = "historical|{}|{}".format(row[4], row[5])
                                type_ = row[6]
                                timestamp = float(row[8])
                                peer_asn = int(row[2])
                                for prefix in self.prefixes:
                                    try:
                                        base_ip, mask_length = this_prefix.split("/")
                                        our_prefix = IPNetwork(prefix)
                                        if (
                                            IPAddress(base_ip) in our_prefix
                                            and int(mask_length) >= our_prefix.prefixlen
                                        ):
                                            msg = {
                                                "type": type_,
                                                "timestamp": timestamp,
                                                "path": as_path,
                                                "service": service,
                                                "communities": communities,
                                                "prefix": this_prefix,
                                                "peer_asn": peer_asn,
                                            }
                                            try:
                                                if validator.validate(msg):
                                                    msgs = normalize_msg_path(msg)
                                                    for msg in msgs:
                                                        key_generator(msg)
                                                        log.debug(msg)
                                                        producer.publish(
                                                            msg,
                                                            exchange=self.update_exchange,
                                                            routing_key="update",
                                                            serializer="ujson",
                                                        )
                                                        time.sleep(0.01)
                                                else:
                                                    log.warning(
                                                        "Invalid format message: {}".format(
                                                            msg
                                                        )
                                                    )
                                            except BaseException:
                                                log.exception(
                                                    "Error when normalizing BGP message: {}".format(
                                                        msg
                                                    )
                                                )
                                            break
                                    except Exception:
                                        log.exception("prefix")
                            except Exception:
                                log.exception("row")
                except Exception:
                    log.exception("exception")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BGPStream Historical Monitor")
    parser.add_argument(
        "-p",
        "--prefixes",
        type=str,
        dest="prefixes_file",
        default=None,
        help="Prefix(es) to be monitored (json file with prefix list)",
    )
    parser.add_argument(
        "-d",
        "--dir",
        type=str,
        dest="dir",
        default=None,
        help="Directory with csvs to read",
    )

    args = parser.parse_args()
    dir_ = args.dir.rstrip("/")
    log.info("Starting BGPstreamhist on {} for {}".format(dir_, args.prefixes_file))

    try:
        bgpstreamhist_instance = BGPStreamHist(args.prefixes_file, dir_)
        bgpstreamhist_instance.parse_bgpstreamhist_csvs()
    except Exception:
        log.exception("exception")
    except KeyboardInterrupt:
        pass
