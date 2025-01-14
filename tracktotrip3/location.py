"""
Location class and methods
"""
from datetime import datetime
import requests
import numpy as np
from sklearn.cluster import DBSCAN
from .point import Point
from .utils import estimate_meters_to_deg


GOOGLE_PLACES_URL = 'https://maps.googleapis.com/maps/api/place/nearbysearch' \
    '/json?location=%s,%s&radius=%s&key=%s'

FOURSQUARE_URL = 'https://api.foursquare.com/v3/places/search?' \
        'll=%f,%f&radius=%d'

GG_CACHE = {}
FS_CACHE = {}

def from_cache(cache, point, threshold, debug = False):
    for entry in list(cache.keys()):
        if point.distance(entry) < threshold:
            return cache[entry]

def google_insert_cache(point, values, debug = False):
    global GG_CACHE
    GG_CACHE[point] = values

def foursquare_insert_cache(point, values, debug = False):
    global FS_CACHE
    FS_CACHE[point] = values


def compute_centroid(points, debug = False):
    """ Computes the centroid of set of points

    Args:
        points (:obj:`list` of :obj:`Point`)
    Returns:
        :obj:`Point`
    """
    lats = [p[1] for p in points]
    lons = [p[0] for p in points]
    return Point(np.mean(lats), np.mean(lons), None)

def update_location_centroid(point, cluster, max_distance, min_samples, debug = False):
    """ Updates the centroid of a location cluster with another point

    Args:
        point (:obj:`Point`): Point to add to the cluster
        cluster (:obj:`list` of :obj:`Point`): Location cluster
        max_distance (float): Max neighbour distance
        min_samples (int): Minimum number of samples
    Returns:
        (:obj:`Point`, :obj:`list` of :obj:`Point`): Tuple with the location centroid
            and new point cluster (given cluster + given point)
    """
    cluster.append(point)
    points = [p.gen2arr() for p in cluster]

    # Estimates the epsilon
    eps = estimate_meters_to_deg(max_distance, precision=6, debug=debug)

    p_cluster = DBSCAN(eps=eps, min_samples=min_samples)
    p_cluster.fit(points)

    clusters = {}
    for i, label in enumerate(p_cluster.labels_):
        if label in list(clusters.keys()):
            clusters[label].append(points[i])
        else:
            clusters[label] = [points[i]]

    centroids = []
    biggest_centroid_l = -float("inf")
    biggest_centroid = None

    for label, n_cluster in list(clusters.items()):
        centroid = compute_centroid(n_cluster, debug)
        centroids.append(centroid)

        if label >= 0 and len(n_cluster) >= biggest_centroid_l:
            biggest_centroid_l = len(n_cluster)
            biggest_centroid = centroid

    if biggest_centroid is None:
        biggest_centroid = compute_centroid(points, debug)

    return biggest_centroid, cluster

def query_foursquare(point, max_distance, key, debug = False):
    """ Queries Squarespace API for a location

    Args:
        point (:obj:`Point`): Point location to query
        max_distance (int): Search radius, in meters
        key (str): Valid Foursquare API key
    Returns:
        :obj:`list` of :obj:`dict`: List of locations with the following format:
            {
                'label': 'Coffee house',
                'distance': 19,
                'types': 'Commerce',
                'suggestion_type': 'FOURSQUARE'
            }
    """
    
    if not key:
        return []

    if from_cache(FS_CACHE, point, max_distance, debug):
        return from_cache(FS_CACHE, point, max_distance, debug)

    headers = {
        'accept': 'application/json',
        'Authorization': key
    }

    url = FOURSQUARE_URL % (point.lat, point.lon, max_distance)
    req = requests.get(url, headers=headers)

    if req.status_code != 200:
        return []
    response = req.json()


    result = []
    results = response['results']

    for res in results:
        name = res['name']
        distance = res['distance']
        categories = [c['name'] for c in res['categories']]
        result.append({
            'label': name,
            'distance': distance,
            'types': categories,
            'suggestion_type': 'FOURSQUARE'
        })

    # final_results = sorted(result, key=lambda elm: elm['distance'])
    foursquare_insert_cache(point, result)
    return result


def query_google(point, max_distance, key, debug = False):
    """ Queries google maps API for a location

    Args:
        point (:obj:`Point`): Point location to query
        max_distance (float): Search radius, in meters
        key (str): Valid google maps api key
    Returns:
        :obj:`list` of :obj:`dict`: List of locations with the following format:
            {
                'label': 'Coffee house',
                'types': 'Commerce',
                'suggestion_type': 'GOOGLE'
            }
    """
    if not key:
        return []

    if from_cache(GG_CACHE, point, max_distance, debug):
        return from_cache(GG_CACHE, point, max_distance, debug)

    req = requests.get(GOOGLE_PLACES_URL % (
        point.lat,
        point.lon,
        max_distance,
        key
    ))

    if req.status_code != 200:
        return []
    
    response = req.json()
    results = response['results']
    # l = len(results)
    final_results = []
    for local in results:
        final_results.append({
            'label': local['name'],
            'distance': Point(local['geometry']['location']['lat'], local['geometry']['location']['lng'], None).distance(point),
            # 'rank': (l-i)/float(l),
            'types': local['types'],
            'suggestion_type': 'GOOGLE'
            })

    google_insert_cache(point, final_results, debug)
    return final_results

def infer_location(
        point,
        location_query,
        max_distance,
        use_google,
        google_key,
        use_foursquare,
        foursquare_key,
        limit, 
        debug = False
    ):
    """ Infers the semantic location of a (point) place.

    Args:
        points (:obj:`Point`): Point location to infer
        location_query: Function with signature, (:obj:`Point`, int) -> (str, :obj:`Point`, ...)
        max_distance (float): Max distance to a position, in meters
        google_key (str): Valid google maps api key
        foursquare_key (str): Valid Foursquare API key
        limit (int): Results limit
    Returns:
        :obj:`Location`: with top match, and alternatives
    """
    locations = []

    if location_query is not None:
        queried_locations = location_query(point, max_distance)
        for (label, centroid, _) in queried_locations:
            locations.append({
                'label': label,
                'distance': centroid.distance(point),
                # 'centroid': centroid,
                'suggestion_type': 'KB'
                })

    api_locations = []
    if len(locations) <= limit:
        if use_google and google_key:
            google_locs = query_google(point, max_distance, google_key, debug)
            api_locations.extend(google_locs)
        if use_foursquare and foursquare_key:
            foursquare_locs = query_foursquare(
                point,
                max_distance,
                foursquare_key,
                debug
            )
            api_locations.extend(foursquare_locs)
    
    if len(api_locations) > 0:
        api_locations = sorted(api_locations, key=lambda d: d['distance'])

    if len(locations) > 0:
        locations = sorted(locations, key=lambda d: d['distance'])
        locations = (locations + api_locations)[:limit]
        return Location(locations[0]['label'], point, locations)
    else:
        return Location('#?', point, api_locations)

class Location(object):
    """ Location representation

    Params:
        label (str): Location name
        centroid (:obj:`Point`): Location position
        other (:obj:`list` of :obj:`dict`): Other possible locations. Includes the current label
    """
    def __init__(self, label, position, other, debug = False):
        self.label = label
        self.centroid = position
        self.other = other
        self.debug = debug

    def distance(self, position):
        """ Computes the distance between centroid and another point

        Args:
            position (:obj:`Point`)
        Returns:
            float: distance, in meters
        """
        return self.centroid.distance(position)

    def to_json(self):
        """ Converts to a json representation

        Returns:
            :obj:`dict`
        """
        return {
            'label': self.label,
            'position': self.centroid.to_json(),
            'other': self.other
        }

    @staticmethod
    def from_json(json, debug = False):
        """ Converts from a json representation

        Returns:
            :obj:`Location`
        """
        return Location(json['label'], json['position'], [], debug)
