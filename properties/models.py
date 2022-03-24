from model_utils import FieldTracker

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from core import models
from search.tasks import stacker_update_address_data, stacker_update_property_data
from sherpa.abstracts import AbstractTag, SingletonModel
from sherpa.utils import sign_street_view_url

User = get_user_model()


class Address(models.Model):
    """
    Address data that is used to provide extra data to prospect or skip trace addresses.

    These addresses are for use in *all* of Sherpa and are not company specific. Anything that is
    specific to a given company should go in the `properties.Property` instead, as that is tied to
    a given company and is used for their prospects.

    Field sizes determined by https://smartystreets.com/docs/cloud/us-street-api
    """
    address = models.CharField(max_length=100)
    city = models.CharField(max_length=64)
    state = models.CharField(max_length=32)
    zip_code = models.CharField(null=True, blank=True, max_length=16)
    zip_plus4 = models.CharField(null=True, blank=True, max_length=4)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    # TODO: add lat/long after adding geodjango

    attom = models.ForeignKey(
        'properties.AttomAssessor', null=True, blank=True, on_delete=models.SET_NULL)

    tracker = FieldTracker()

    class Meta:
        # Setting unique address https://smartystreets.com/docs/addresses-have-unique-identifier
        unique_together = ('address', 'city', 'state')

        # Set the combined index as we will be searching on these three fields combined.
        indexes = [
            models.Index(fields=['address', 'city', 'state']),
        ]

    @property
    def full_zip_code(self):
        return self.zip_code if not self.zip_plus4 else f'{self.zip_code}-'

    @property
    def address_display(self):
        address = f'{self.address}, {self.city}, {self.state}'
        if self.zip_code:
            address += f' {self.full_zip_code}'
        return address

    @property
    def zillow_link(self):
        zip_code = ""
        if self.zip_code is not None:
            zip_code = self.zip_code.replace(" ", "+")
        return "%s%s-%s-%s-%s%s" % (
            "https://www.zillow.com/homes/",
            self.address.replace(" ", "+"),
            self.city.replace(" ", "+"),
            self.state.replace(" ", "+"),
            zip_code,
            "_rb/",
        )

    @property
    def street_view_url(self):
        """
        Return the street view url if it's available.

        [Developer Guide](https://developers.google.com/maps/documentation/streetview/intro)
        """
        api_key = settings.GOOGLE_STREET_VIEW_API_KEY
        secret = settings.GOOGLE_STREET_VIEW_SECRET

        if not api_key or not secret or not self.address_display:
            return None

        # Generate the unsigned url to be used in generating the signature.
        location = f'?location={self.address_display}'
        size = '&size=500x500'
        key = f'&key={api_key}'

        # Now we can sign the url and return it.
        unsigned_url = f'/maps/api/streetview{location}{size}{key}'.replace(' ', '%20')
        return sign_street_view_url(unsigned_url, secret)

    @property
    def prospects(self):
        """
        Returns a queryset of all prospects that use this address.
        """
        from sherpa.models import Prospect
        return Prospect.objects.filter(Q(prop__address=self) | Q(prop__mailing_address=self))

    def save(self, *args, **kwargs):
        if self.tracker.changed() and self.pk:
            # Update the stacker index.
            changes = {}
            attom_changed = False
            for field in self.tracker.changed().keys():
                if field == "attom_id":
                    attom_changed = True
                    continue
                changes[field] = getattr(self, field)

            if attom_changed:
                changes["last_sold_date"] = self.attom.deed_last_sale_date
            if changes:
                stacker_update_address_data.delay(self.id, changes)
        super().save(*args, **kwargs)


class PropertyTag(AbstractTag):
    """
    Allows companies to assign tags for grouping and filtering properties.
    """
    distress_indicator = models.BooleanField(
        help_text="Determines if the tag is associated with linking a property to extra distress.")

    @property
    def prospect_count(self):
        from sherpa.models import Prospect
        return Prospect.objects.filter(prop__tags=self).count()

    @property
    def property_count(self):
        return self.property_set.count()


class Property(models.Model):
    """
    Represents a property for a company, which can have multiple prospects.
    """
    created = models.DateTimeField(default=timezone.now)
    last_modified = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(null=True)
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name='properties')
    mailing_address = models.ForeignKey(
        Address,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='mailing_properties',
    )
    is_charged = models.BooleanField(
        blank=True,
        null=True,
        help_text='Indicates Property has already been charged in a push to campaign.',
    )
    tags = models.ManyToManyField(PropertyTag, through='PropertyTagAssignment')

    upload_skip_trace = models.ForeignKey(
        'sherpa.UploadSkipTrace',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    upload_prospects = models.ForeignKey(
        'sherpa.UploadProspects',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    tracker = FieldTracker(fields=['address_id', 'is_archived'])

    class Meta:
        unique_together = ('company', 'address')

    def get_stacker_data(self):
        lsd = self.address.attom.deed_last_sale_date if self.address.attom else None
        return {
            'address_id': self.address_id,
            'address': self.address.address,
            'city': self.address.city,
            'state': self.address.state,
            'zip_code': self.address.zip_code,
            'last_sold_date': lsd,
        }

    def save(self, *args, **kwargs):
        self.last_modified = timezone.now()
        if self.tracker.changed() and self.pk:
            # update stacker index
            changes = {}
            if self.tracker.has_changed('address_id'):
                changes = self.get_stacker_data()
            if self.tracker.has_changed('is_archived'):
                changes['is_archived'] = self.is_archived
            if changes:
                stacker_update_property_data.delay(self.id, changes)
        return super().save(*args, **kwargs)

    @property
    def last_contact(self):
        """
        Returns the last time this property has been contacted.
        """
        if not self.prospect_set.first():
            return None
        return self.prospect_set.first().last_sms_sent_utc

    @property
    def get_quitclaim_flag(self):
        try:
            if self.address.attom_id:
                attom_recorder_object = AttomRecorder.objects.filter(
                    attom_id=self.address.attom_id).first()
                return attom_recorder_object.quitclaim_flag
        except Exception:
            return None

    @property
    def get_available_equity(self):
        try:
            if self.address.attom_id:
                attom_loan_object = AttomLoan.objects.get(attom_id=self.address.attom_id)
                return attom_loan_object.available_equity
        except Exception:
            return None


class AddressLastValidated(SingletonModel):
    """
    Track Property ID of address last validated.
    """
    property_id = models.IntegerField(blank=True, null=True)
    last_checked = models.DateTimeField(auto_now=True)


class PropertyTagAssignment(models.Model):
    """
    Relation between property and tag allowing to add extra data about when the tag was assigned.
    """
    tag = models.ForeignKey(PropertyTag, on_delete=models.CASCADE)
    prop = models.ForeignKey(Property, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('tag', 'prop')

    def __str__(self):
        return f'{self.tag.name} on {self.assigned_at}'


class AttomAssessor(models.Model):
    PROPERTY_GROUP_CHOICES = (
        ("UNKNOWN", "UNKNOWN OR NOT PROVIDED"),
        ("Commercial", "The general use for the property is for commercial purposes"),
        ("Other", "The general use for the property is for uses other than Residential or Commercial"),  # noqa: E501
        ("Residential", "The general use for the property is for residential purposes"),
    )

    PARKING_GARAGE_CHOICES = (
        (None, "UNKNOWN OR NOT PROVIDED"),
        ("0", "UNKNOWN"),
        ("1", "UNKNOWN OR NOT PROVIDED"),
        ("4", "Pole Building Garage"),
        ("11", "Garage, Attached"),
        ("12", "Garage, Detached"),
        ("13", "Garage, Unfinished"),
        ("14", "Garage, Finished"),
        ("15", "Garage, Enclosed"),
        ("16", "Garage, Open"),
        ("17", "Detached (Unspecified)"),
        ("18", "Attached (Unspecified)"),
        ("19", "Detached, Finished"),
        ("20", "Detached, Unfinished"),
        ("21", "Attached, Finished"),
        ("22", "Attached, Unfinished"),
        ("23", "Detached, 1-Car"),
        ("24", "Detached, 2-Car"),
        ("25", "Detached, 3+ Car"),
        ("26", "Attached, 1-Car"),
        ("27", "Attached, 2-Car"),
        ("28", "Attached, 3+ Car"),
        ("30", "Carport (Unspecified)"),
        ("31", "Carport, Attached"),
        ("32", "Carport, Detached"),
        ("33", "Carport, Enclosed"),
        ("34", "Carport, Open"),
        ("35", "Carport, 1-Car"),
        ("36", "Carport, 2-Car"),
        ("37", "Carport, 3+ Car"),
        ("38", "Carport, Finished"),
        ("39", "Carport, Unfinished"),
        ("40", "Garage, Basement"),
        ("41", "Garage, Basement, 1-Car"),
        ("42", "Garage, Basement, 2-Car"),
        ("43", "Garage, Basement, 3+ Car"),
        ("44", "Garage, Basement, Finished"),
        ("45", "Garage, Basement, Finished, 1-Car"),
        ("46", "Garage, Basement, Finished, 2-Car"),
        ("47", "Garage, Basement, Finished, 3+ Car"),
        ("48", "Garage, Basement, Unfinished"),
        ("49", "Garage, Basement, Unfinished, 1-Car"),
        ("50", "Garage, Basement, Unfinished, 2-Car"),
        ("51", "Garage, Basement, Unfinished, 3+ Car"),
        ("52", "Garage, Tuckunder"),
        ("53", "Garage, Built-in"),
        ("54", "Garage, Built-in, 1-Car"),
        ("55", "Garage, Built-in, 2-Car"),
        ("57", "Garage, Built-in, Unfinished"),
        ("58", "Garage, Built-in, Finished"),
        ("59", "Garage, 1-Car"),
        ("60", "Garage, 2-Car"),
        ("61", "Garage, 3+ Car"),
        ("62", "Garage, Unfinished, 1-Car"),
        ("63", "Garage, Unfinished, 2-Car"),
        ("64", "Garage, Unfinished, 3+ Car"),
        ("65", "Carport, Detached, Finished"),
        ("67", "Carport, Detached, Unfinished"),
        ("68", "Covered"),
        ("69", "Mixed"),
        ("70", "Garage, Heated"),
        ("189", "Parking Structure"),
        ("999", "Type Not Specified"),
    )

    PROPERTY_USE_STANDARDIZED_CHOICES = (
        (None, "UNKNOWN OR NOT PROVIDED"),
        ("0", "UNKNOWN"),
        ("101", "DAIRY FARM"),
        ("102", "DESERT OR BARREN LAND"),
        ("103", "FARM, CROPS"),
        ("104", "FEEDLOTS"),
        ("105", "FARM (IRRIGATED OR DRY)"),
        ("106", "HORTICULTURE, ORNAMENTAL (AGRICULTURAL)"),
        ("107", "IRRIGATION, FLOOD CONTROL"),
        ("108", "LIVESTOCK, ANIMALS"),
        ("109", "MISCELLANEOUS STRUCTURES - RANCH, FARM FIXTURES"),
        ("110", "ORCHARD (FRUIT, NUT)"),
        ("111", "ORCHARDS, GROVES"),
        ("112", "PASTURE"),
        ("113", "POULTRY FARM (CHICKEN, TURKEY, FISH, BEES, RABBITS)"),
        ("114", "RANCH"),
        ("115", "RESERVOIR, WATER SUPPLY"),
        ("116", "RURAL IMPROVED / NON-RESIDENTIAL"),
        ("117", "RANGE LAND (GRAZING)"),
        ("118", "AGRICULTURAL/RURAL (GENERAL)"),
        ("119", "TRUCK CROPS"),
        ("120", "TIMBERLAND, FOREST, TREES"),
        ("121", "VINEYARD"),
        ("122", "WELL SITE (AGRICULTURAL)"),
        ("123", "WILDLIFE (REFUGE)"),
        ("124", "CONVENIENCE STORE (7-11)"),
        ("125", "APPLIANCE STORE (CIRCUIT CITY, GOODS BUYS, BEST BUY)"),
        ("126", "AUTO REPAIR, GARAGE"),
        ("127", "VEHICLE SALES, VEHICLE RENTALS (AUTO/TRUCK/RV/BOAT/ETC)"),
        ("128", "BAKERY"),
        ("129", "BAR, TAVERN"),
        ("130", "COMMERCIAL BUILDING, MAIL ORDER, SHOW ROOM (NON-AUTO), WAREHOUSE"),
        ("131", "BED & BREAKFAST"),
        ("132", "CASINO"),
        ("133", "CEMETERY, FUNERAL HOME, MORTUARY (COMMERCIAL)"),
        ("134", "COMMON AREA (COMMERCIAL, NOT SHOPPING CENTER)"),
        ("135", "COMMERCIAL (GENERAL)"),
        ("136", "COMMERCIAL OFFICE (GENERAL)"),
        ("137", "CONVENIENCE STORE (W/FUEL PUMP)"),
        ("138", "COMMERCIAL CONDOMINIUM (NOT OFFICES)"),
        ("139", "CONDOMINIUM OFFICES"),
        ("140", "STORE/OFFICE (MIXED USE)"),
        ("141", "DEPARTMENT STORE (APPAREL, HOUSEHOLD GOODS, FURNITURE)"),
        ("142", "DENTAL BUILDING"),
        ("143", "DEPARTMENT STORE (MULTI-STORY)"),
        ("144", "GARDEN CENTER, HOME IMPROVEMENT (DO-IT-YOURSELF)"),
        ("145", "DRUG STORE, PHARMACY"),
        ("146", "DRIVE-THRU RESTAURANT, FAST FOOD"),
        ("147", "DRY CLEANER"),
        ("148", "RESTAURANT"),
        ("149", "FARM SUPPLY & EQUIPMENT (COMMERCIAL)"),
        ("150", "FINANCIAL BUILDING"),
        ("151", "GROCERY, SUPERMARKET"),
        ("152", "HOSPITAL - PRIVATE"),
        ("153", "HOTEL/MOTEL"),
        ("154", "HOTEL-RESORT"),
        ("155", "HOTEL"),
        ("156", "KENNEL"),
        ("157", "LAUNDROMAT (SELF-SERVICE)"),
        ("158", "LIQUOR STORE"),
        ("159", "MOBILE COMMERCIAL UNITS"),
        ("160", "MEDICAL BUILDING"),
        ("161", "MIXED USE (COMMERCIAL/INDUSTRIAL)"),
        ("162", "MOBILE HOME PARK, TRAILER PARK"),
        ("163", "MOTEL"),
        ("164", "COMMERCIAL MULTI-PARCEL MISCELLANEOUS"),
        ("165", "COMMERCIAL MISCELLANEOUS"),
        ("166", "NIGHTCLUB (COCKTAIL LOUNGE)"),
        ("167", "NEIGHBORHOOD: SHOPPING CENTER, STRIP CENTER, ENTERPRISE ZONE"),
        ("168", "NURSERY, GREENHOUSE, FLORIST (RETAIL, WHOLESALE)"),
        ("169", "OFFICE BUILDING"),
        ("170", "OFFICE BUILDING (MULTI-STORY)"),
        ("171", "COMMERCIAL OFFICE/RESIDENTIAL (MIXED USE)"),
        ("172", "PARKING GARAGE, PARKING STRUCTURE"),
        ("173", "PRINTER - RETAIL (PIP, QWIKCOPY, ETC)"),
        ("174", "PARKING LOT"),
        ("175", "DAY CARE, PRE-SCHOOL (COMMERCIAL)"),
        ("176", "PROFESSIONAL BUILDING (MULTI-STORY)"),
        ("177", "PROFESSIONAL BUILDING (LEGAL, INSURANCE, REAL ESTATE, BUSINESS)"),
        ("178", "RETAIL STORES (PERSONAL SERVICES, PHOTOGRAPHY, TRAVEL)"),
        ("179", "REGIONAL: SHOPPING CENTER, MALL (W/ANCHOR)"),
        ("180", "GAS STATION"),
        ("181", "SINGLE FAMILY RESIDENTIAL"),
        ("182", "SHOPPING CENTER COMMON AREA (PARKING ETC)"),
        ("183", "COMMUNITY: SHOPPING CENTER, MINI-MALL"),
        ("184", "SKYSCRAPER/HIGH-RISE (COMMERCIAL OFFICES)"),
        ("185", "SERVICE STATION W/CONVENIENCE STORE (FOOD MART)"),
        ("186", "SERVICE STATION (FULL SERVICE)"),
        ("187", "STORES & APARTMENTS"),
        ("188", "STORE, RETAIL OUTLET"),
        ("189", "TAKE-OUT RESTAURANT (FOOD PREPARATION)"),
        ("190", "TRUCK STOP (FUEL AND DINER)"),
        ("191", "SERVICE SHOP (TV, RADIO, ELECTRIC, PLUMBING)"),
        ("192", "VETERINARY, ANIMAL HOSPITAL"),
        ("193", "CAR WASH"),
        ("194", "WHOLESALE OUTLET, DISCOUNT STORE (FRANCHISE)"),
        ("195", "ASSEMBLY (LIGHT INDUSTRIAL)"),
        ("196", "BULK STORAGE, TANKS (GASOLINE, FUEL, ETC)"),
        ("197", "CANNERY"),
        ("198", "CONSTRUCTION/CONTRACTING SERVICES (INDUSTRIAL)"),
        ("199", "CHEMICAL"),
        ("200", "COMMON AREA (INDUSTRIAL)"),
        ("201", "CONDOMINIUMS (INDUSTRIAL)"),
        ("202", "COLD STORAGE"),
        ("203", "DISTILLERY, BREWERY, BOTTLING"),
        ("204", "DUMP SITE"),
        ("205", "FACTORY (APPAREL, TEXTILE, LEATHER, MEDIUM MFG)"),
        ("206", "FOOD PROCESSING"),
        ("207", "FOUNDRY, INDUSTRIAL PLANT (METAL, RUBBER, PLASTIC)"),
        ("208", "FOOD PACKING, PACKING PLANT (FRUIT, VEGETABLE, MEAT, DAIRY)"),
        ("209", "GRAIN ELEVATOR"),
        ("210", "HEAVY INDUSTRIAL (GENERAL)"),
        ("211", "HEAVY MANUFACTURING"),
        ("212", "INDUSTRIAL (GENERAL)"),
        ("213", "INDUSTRIAL PARK"),
        ("214", "LABOR CAMPS (INDUSTRIAL)"),
        ("215", "LIGHT INDUSTRIAL (10% IMPROVED OFFICE SPACE; MACHINE SHOP)"),
        ("216", "INDUSTRIAL LOFT BUILDING, LOFT BUILDING"),
        ("217", "LUMBERYARD, BUILDING MATERIALS"),
        ("218", "LUMBER & WOOD PRODUCT MFG (INCLUDING FURNITURE)"),
        ("219", "MARINE FACILITY/BOARD REPAIRS (SMALL CRAFT, SAILBOAT)"),
        ("220", "MANUFACTURING (LIGHT)"),
        ("221", "MILL (FEED, GRAIN, PAPER, LUMBER, TEXTILE, PULP"),
        ("222", "MINING, MINERAL, QUARRIES"),
        ("223", "INDUSTRIAL MISCELLANEOUS"),
        ("224", "MULTI-TENANT INDUSTRIAL BUILDING"),
        ("225", "PAPER PRODUCT MFG & RELATED PRODUCTS"),
        ("226", "REFINERY, PETROLEUM PRODUCTS"),
        ("227", "PRINTING * PUBLISHING (LIGHT INDUSTRIAL)"),
        ("228", "PROCESSING PLANT (MINERALS, CEMENT, ROCK, GRAVEL, GLASS, CLAY)"),
        ("229", "MINI-WAREHOUSE, STORAGE"),
        ("230", "QUARRIES (SAND, GRAVEL, ROCK)"),
        ("231", "R&D FACILITY, LABORATORY, RESEARCH FACILITY, COSMETICS, PHARMACEUTICAL"),
        ("232", "RECYCLING (METAL, PAPER, GLASS)"),
        ("233", "SHIPYARD - BUILT OR REPAIRED (SEAGOING VESSELS)"),
        ("234", "SLAUGHTER HOUSE, STOCKYARD"),
        ("235", "STORAGE YARD (JUNK, AUTO WRECKING, SALVAGE)"),
        ("236", "STORAGE YARD, OPEN STORAGE (LIGHT EQUIPMENT, MATERIAL)"),
        ("237", "SUGAR REFINERY"),
        ("238", "WAREHOUSE, STORAGE"),
        ("239", "WINERY"),
        ("240", "WASTE DISPOSAL, SEWAGE (PROCESSING, DISPOSAL, STORAGE, TREATMENT)"),
        ("241", "COMMON AREA (MISC)"),
        ("242", "EASEMENT (MISC)"),
        ("243", "HOMESTEAD (MISC)"),
        ("244", "LEASEHOLD RIGHTS (MISC)"),
        ("245", "PETROLEUM & GAS WELLS (MISC)"),
        ("246", "PIPELINE OR RIGHT-OF-WAY"),
        ("247", "POSSESSORY INTEREST (MISC)"),
        ("248", "RAIL (RIGHT-OF-WAY & TRACK)"),
        ("249", "ROAD (RIGHT-OF-WAY)"),
        ("250", "ROYALTY INTEREST"),
        ("251", "RIGHT-OF-WAY (NOT RAIL, ROAD OR UTILITY)"),
        ("252", "SUB-SURFACE RIGHTS (MINERAL)"),
        ("253", "SURFACE RIGHTS (GRAZING, TIMBER, COAL, ETC.)"),
        ("254", "UNKNOWN"),
        ("255", "UTILITIES (RIGHT-OF-WAY ONLY)"),
        ("256", "WATER RIGHTS (MISC)"),
        ("257", "WORKING INTEREST"),
        ("258", "AIRPORT & RELATED"),
        ("259", "ARCADES (AMUSEMENT)"),
        ("260", "ARENA, CONVENTION CENTER"),
        ("261", "AUDITORIUM"),
        ("262", "OUTDOOR RECREATION: BEACH, MOUNTAIN, DESERT"),
        ("263", "POOL HALL, BILLIARD PARLOR"),
        ("264", "BOWLING ALLEY"),
        ("265", "BUS TERMINAL"),
        ("266", "COMMERCIAL AUTO TRANSPORTATION/STORAGE"),
        ("267", "COUNTRY CLUB"),
        ("268", "CENTRALLY ASSESSED"),
        ("269", "CHARITABLE ORGANIZATION, FRATERNAL"),
        ("270", "CLUBS, LODGES, PROFESSIONAL ASSOCIATIONS"),
        ("271", "COMMUNITY CENTER (EXEMPT)"),
        ("272", "COMMUNICATIONS"),
        ("273", "CAMPGROUND, RV PARK"),
        ("274", "COLLEGE, UNIVERSITY, VOCATIONAL SCHOOL - PRIVATE"),
        ("275", "CREMATORIUM, MORTUARY (EXEMPT)"),
        ("276", "CABLE TV STATION"),
        ("277", "CITY, MUNICIPAL, TOWN, VILLAGE OWNED (EXEMPT)"),
        ("278", "COUNTY OWNED (EXEMPT)"),
        ("279", "DANCE HALL"),
        ("280", "DISTRIBUTION WAREHOUSE (REGIONAL)"),
        ("281", "DRIVE-IN THEATER"),
        ("282", "CEMETERY (EXEMPT)"),
        ("283", "EMERGENCY (POLICE, FIRE, RESCUE, SHELTERS, ANIMAL SHELTER)"),
        ("284", "EXEMPT (FULL OR PARTIAL)"),
        ("285", "FAIRGROUNDS"),
        ("286", "FEDERAL PROPERTY (EXEMPT)"),
        ("287", "FISH CAMPS, GAME CLUB TARGET SHOOTING"),
        ("288", "FOREST (PARK, RESERVE, RECREATION, CONSERVATION)"),
        ("289", "FREEWAYS, STATE HWYS"),
        ("290", "DRIVING RANGE (GOLF)"),
        ("291", "TRANSPORTATION (GENERAL)"),
        ("292", "GO-CARTS, MINIATURE GOLD, WATER SLIDES"),
        ("293", "GOLF COURSE"),
        ("294", "GOVERNMENTAL / PUBLIC USE (GENERAL)"),
        ("295", "GOVT. ADMINISTRATIVE OFFICE (FEDERAL, STATE, LOCAL, COURT HOUSE)"),
        ("296", "GYM, HEALTH SPA"),
        ("297", "HISTORICAL DISTRICT"),
        ("298", "CULTURAL, HISTORICAL (MONUMENTS, HOMES, MUSEUMS, OTHER)"),
        ("299", "HISTORICAL TRANSIENT LODGING (HOTEL, MOTEL)"),
        ("300", "HARBOR & MARINE TRANSPORTATION"),
        ("301", "HISTORICAL OFFICE"),
        ("302", "HOSPITAL - PUBLIC"),
        ("303", "HISTORICAL PARK, SITE, MISC."),
        ("304", "HISTORICAL - PRIVATE (GENERAL)"),
        ("305", "HISTORICAL RECREATION, ENTERTAINMENT"),
        ("306", "HISTORICAL RESIDENCE"),
        ("307", "HISTORICAL RETAIL"),
        ("308", "HISTORICAL WAREHOUSE"),
        ("309", "INDIAN LANDS"),
        ("310", "INSTITUTIONAL (GENERAL)"),
        ("311", "MARINA, BOAT SLIPS, YACHT CLUB, BOAT LANDING"),
        ("312", "MEDICAL CLINIC"),
        ("313", "MICROWAVE"),
        ("314", "MILITARY (OFFICE, BASE, POST, PORT, RESERVE, WEAPON RANGE, TEST SITES)"),
        ("315", "MISCELLANEOUS (GENERAL)"),
        ("316", "MUSEUM, LIBRARY, ART GALLERY (RECREATIONAL)"),
        ("317", "NATURAL RESOURCES"),
        ("318", "RECREATIONAL NON-TAXABLE (CAMPS, BOY SCOUTS)"),
        ("319", "CORRECTIONAL FACILITY, JAILS, PRISONS, INSANE ASYLUM"),
        ("320", "CHILDREN'S HOME, ORPHANAGE"),
        ("321", "PUBLIC HEALTH CARE FACILITY (EXEMPT)"),
        ("322", "PARK, PLAYGROUND, PICNIC AREA"),
        ("323", "PIERS, WHARF (RECREATION)"),
        ("324", "POLLUTION CONTROL"),
        ("325", "POST OFFICE"),
        ("326", "PUBLIC SWIMMING POOL"),
        ("327", "AMUSEMENT PARK, TOURIST ATTRACTION"),
        ("328", "PAROCHIAL SCHOOL, PRIVATE SCHOOL"),
        ("329", "PUBLIC UTILITY (ELECTRIC, WATER, GAS, ETC.)"),
        ("330", "RAILROAD & RELATED"),
        ("331", "RACQUET COURT, TENNIS COURT"),
        ("332", "RECREATIONAL CENTER"),
        ("333", "REGULATING DISTRICTS & ASSESSMENTS; TAX ABATEMENT"),
        ("334", "RECREATIONAL/ENTERTAINMENT (GENERAL)"),
        ("335", "REDEVELOPMENT AGENCY OR ZONE"),
        ("336", "RELIGIOUS, CHURCH, WORSHIP (SYNAGOGUE, TEMPLE, PARSONAGE)"),
        ("337", "RIDING STABLE, TRAILS"),
        ("338", "ROADS, STREETS, BRIDGES"),
        ("339", "HOMES (RETIRED, HANDICAP, REST, CONVALESCENT, NURSING)"),
        ("340", "RADIO OR TV STATION"),
        ("341", "SBE - SPECIAL ASSESSMENTS"),
        ("342", "PUBLIC SCHOOL (ADMINISTRATION, CAMPUS, DORMS, INSTRUCTION)"),
        ("343", "SKATING RINK, ICE SKATING, ROLLER SKATING"),
        ("344", "STATE OWNED (EXEMPT)"),
        ("345", "SPECIAL PURPOSE"),
        ("346", "STADIUM"),
        ("347", "TELEGRAPH, TELEPHONE"),
        ("348", "THEATER (MOVIE)"),
        ("349", "TRANSPORTATION (AIR, RAIL, BUS)"),
        ("350", "RACE TRACK (AUTO, DOG, HORSE)"),
        ("351", "TRUCK TERMINAL (MOTOR FREIGHT)"),
        ("352", "COLLEGES, UNIVERSITY - PUBLIC"),
        ("353", "PRIVATE UTILITY (ELECTRIC, WATER, GAS, ETC.)"),
        ("354", "WELFARE, SOCIAL SERVICE, LOW INCOME HOUSING (EXEMPT)"),
        ("355", "ZOO"),
        ("356", "OTHER EXEMPT PROPERTY"),
        ("357", "GARDEN APT, COURT APT (5+ UNITS)"),
        ("358", "HIGH-RISE APARTMENTS"),
        ("359", "APARTMENT HOUSE (100+ UNITS)"),
        ("360", "APARTMENTS (GENERIC)"),
        ("361", "APARTMENT HOUSE (5+ UNITS)"),
        ("362", "BOARDING/ROOMING HOUSE, APT HOTEL"),
        ("363", "BUNGALOW (RESIDENTIAL)"),
        ("364", "CLUSTER HOME"),
        ("365", "COMMON AREA (RESIDENTIAL)"),
        ("366", "CONDOMINIUM"),
        ("367", "COOPERATIVE"),
        ("368", "DORMITORY, GROUP QUARTERS (RESIDENTIAL)"),
        ("369", "DUPLEX (2 UNITS, ANY COMBINATION)"),
        ("370", "FRATERNITY HOUSE, SORORITY HOUSE"),
        ("371", "MANUFACTURED, MODULAR, PRE-FABRICATED HOMES"),
        ("372", "MULTI-FAMILY DWELLINGS (GENERIC, ANY COMBINATION)"),
        ("373", "MOBILE HOME"),
        ("374", "RESIDENTIAL MULTI-PARCEL MISCELLANEOUS"),
        ("375", "MISCELLANEOUS (RESIDENTIAL)"),
        ("376", "PATIO HOME"),
        ("377", "PLANNED UNIT DEVELOPMENT (PUD)"),
        ("378", "QUADPLEX (4 UNITS, ANY COMBINATION)"),
        ("379", "CONDOMINIUM DEVELOPMENT (ASSOCIATION ASSESSMENT)"),
        ("380", "RESIDENTIAL (GENERAL/SINGLE)"),
        ("381", "RESIDENTIAL INCOME (GENERAL/MULTI-FAMILY)"),
        ("382", "ROW HOUSE"),
        ("383", "RURAL RESIDENCE"),
        ("384", "SEASONAL, CABIN, VACATION RESIDENCE"),
        ("385", "SINGLE FAMILY RESIDENCE"),
        ("386", "TOWNHOUSE"),
        ("387", "TIMESHARE"),
        ("388", "TRIPLEX (3 UNITS, ANY COMBINATION)"),
        ("389", "VACANT LAND"),
        ("390", "ZERO LOT LINE (RESIDENTIAL)"),
        ("391", "ABANDONED SITE, CONTAMINATED SITE"),
        ("392", "AGRICULTURAL (UNIMPROVED) - VACANT LAND"),
        ("393", "VACANT COMMERCIAL"),
        ("394", "GOVERNMENT - VACANT LAND"),
        ("395", "INDUSTRIAL - VACANT LAND"),
        ("396", "INSTITUTIONAL - VACANT LAND"),
        ("397", "VACANT"),
        ("398", "MULTI-FAMILY - VACANT LAND"),
        ("399", "PRIVATE PRESERVE, OPEN SPACE - VACANT LAND"),
        ("400", "RECREATIONAL - VACANT LAND"),
        ("401", "RESIDENTIAL - VACANT LAND"),
        ("402", "UNDER CONSTRUCTION"),
        ("403", "UNUSABLE LAND (REMNANT, STEEP, ETC.)"),
        ("404", "WASTE LAND, MARSH, SWAMP, SUBMERGED - VACANT LAND"),
        ("406", "WATER AREA (LAKES, RIVER, SHORE) - VACANT LAND"),
        ("407", "COMMON AREA (MISC.)"),
        ("408", "TEMPORARY STRUCTURES"),
        ("409", "VACANT LAND - EXEMPT"),
        ("410", "SPORTS COMPLEX"),
        ("411", "PERSONAL PROPERTY (GENERAL)"),
        ("412", "PET BOARDING & GROOMING"),
        ("413", "CROPS (IN GROUND)"),
        ("414", "STRUCTURES (GENERAL)"),
        ("415", "AIRCRAFT"),
        ("416", "LANDOMINIUM"),
        ("417", "SURFACE RIGHTS (GRAZING, TIMBER, COAL, ETC.)"),
        ("418", "RESIDENTIAL PARKING GARAGE"),
        ("419", "INVENTORY"),
        ("420", "MOTOR VEHICLES (CARS, TRUCKS, ETC.)"),
        ("421", "CONDOMINIUM BUILDING (RESIDENTIAL)"),
        ("422", "MISC STRUCTURES NOT OTHERWISE CLASSED (BILLBOARDS, ETC.)"),
        ("423", "BARNDOMINIUM"),
        ("424", "SUB-SURFACE RIGHTS (MINERAL)"),
        ("425", "GOODS IN TRANSIT"),
        ("426", "RIGHT-OF-WAY (NOT RAIL, ROAD OR UTILITY)"),
        ("427", "SPACECRAFT"),
        ("428", "RAIL (RIGHT-OF-WAY & TRACK)"),
        ("429", "STRUCTURES ON LEASED LAND"),
        ("430", "ROYALTY INTEREST"),
        ("431", "POSSESSORY INTEREST (MISC.)"),
        ("432", "WATERCRAFT (SHIPS, BOATS, PWCS, ETC.)"),
        ("433", "CAR WASH - SELF-SERVE"),
        ("434", "ROLLING STOCK (RAILROAD)"),
        ("435", "WATER RIGHTS (MISC.)"),
        ("436", "MISC PERSONAL PROPERTY NOT OTHERWISE CLASSED"),
        ("437", "INTANGIBLE PERSONAL PROPERTY"),
        ("438", "LEASEHOLD RIGHTS (MISC.)"),
        ("439", "MISC. BUSINESS PERSONAL PROPERTY NOT OTHERWISE CLASSED"),
        ("440", "HOMESTEAD (MISC.)"),
        ("441", "VEHICLES (GENERAL)"),
        ("442", "UTILITIES (RIGHT-OF-WAY ONLY)"),
        ("443", "PIPELINE OR RIGHT-OF-WAY"),
        ("444", "MISC VEHICLES NOT OTHERWISE CLASSED (ANTIQUES, ETC.)"),
        ("445", "BUSINESS PERSONAL PROPERTY (GENERAL)"),
        ("446", "CROPS (HARVESTED)"),
        ("447", "TINY HOUSE"),
        ("448", "RESIDENTIAL STORAGE SPACE"),
        ("449", "ROADSIDE MARKET"),
        ("450", "CANNABIS GROW FACILITY"),
        ("451", "CELLULAR"),
        ("452", "GARDEN HOME"),
        ("453", "VACANT LAND - DESTROYED/UNINHABITABLE IMPROVEMENT"),
        ("454", "ROAD (RIGHT-OF-WAY)"),
        ("455", "EQUIPMENT / SUPPLIES"),
        ("456", "PETROLEUM & GAS WELLS (MISC.)"),
        ("457", "WORKING INTEREST"),
        ("458", "CAR WASH - AUTOMATED"),
        ("459", "CANNABIS DISPENSARY"),
        ("460", "RECREATIONAL VEHICLES / TRAVEL TRAILERS"),
        ("461", "COOPERATIVE BUILDING (RESIDENTIAL)"),
        ("462", "VACANT LAND - UNSPECIFIED IMPROVEMENT"),
        ("463", "PARCELS WITH IMPROVEMENTS, USE NOT SPECIFIED"),
        ("464", "BARBER/HAIR SALON"),
        ("465", "EASEMENT (MISC.)"),
        ("466", "LIVESTOCK (ANIMALS, FISH, BIRDS, ETC.)"),
    )

    OWNER_TYPE_DESCRIPTION_1_CHOICES = (
        (None, "UNKNOWN OR NOT PROVIDED"),
        ("Individual", "Owned by a person, couple or some non-incorporated entity"),
        ("Company", " Company"),
        ("Deceased", "The owner is deceased"),
        ("Unknown", "Unable to determine the owner type"),
        ("Government", "Owned by a Federal, State or Local governmental agency or entity"),
    )

    attom_id = models.PositiveIntegerField(primary_key=True)

    # Property address
    property_address_full = models.CharField(null=True, blank=True, max_length=150)
    property_address_house_number = models.CharField(null=True, blank=True, max_length=25)
    property_address_street_direction = models.CharField(null=True, blank=True, max_length=10)
    property_address_street_name = models.CharField(null=True, blank=True, max_length=100)
    property_address_street_suffix = models.CharField(null=True, blank=True, max_length=25)
    property_address_street_post_direction = models.CharField(null=True, blank=True, max_length=10)
    property_address_unit_prefix = models.CharField(null=True, blank=True, max_length=20)
    property_address_unit_value = models.CharField(null=True, blank=True, max_length=25)
    property_address_city = models.CharField(null=True, blank=True, max_length=50)
    property_address_state = models.CharField(null=True, blank=True, max_length=2)
    property_address_zip = models.CharField(null=True, blank=True, max_length=5)
    property_address_zip4 = models.CharField(null=True, blank=True, max_length=4)
    legal_description = models.CharField(null=True, blank=True, max_length=255)

    # Party owner
    party_owner_1name_first = models.CharField(null=True, blank=True, max_length=50)
    party_owner_1name_last = models.CharField(null=True, blank=True, max_length=50)

    # Owner Type
    owner_type_description_1 = models.CharField(
        null=True, blank=True, max_length=50, choices=OWNER_TYPE_DESCRIPTION_1_CHOICES)

    # Built year
    year_built = models.PositiveSmallIntegerField(blank=True, null=True)
    year_built_effective = models.PositiveSmallIntegerField(blank=True, null=True)

    # Property use
    property_use_group = models.CharField(
        null=True, blank=True, max_length=50, choices=PROPERTY_GROUP_CHOICES)
    property_use_standardized = models.CharField(
        null=True, blank=True, max_length=4, choices=PROPERTY_USE_STANDARDIZED_CHOICES)

    # Last deed
    deed_last_sale_date = models.DateField(blank=True, null=True)
    deed_last_sale_price = models.DecimalField(
        max_digits=20, decimal_places=4, blank=True, null=True)

    # Size
    area_gross = models.PositiveIntegerField(blank=True, null=True)
    area_1st_floor = models.PositiveIntegerField(blank=True, null=True)
    area_2nd_floor = models.PositiveIntegerField(blank=True, null=True)
    area_upper_floors = models.PositiveIntegerField(blank=True, null=True)
    area_lot_acres = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    area_lot_sf = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    parking_garage = models.CharField(
        null=True, blank=True, max_length=4, choices=PARKING_GARAGE_CHOICES)
    parking_garage_area = models.PositiveIntegerField(blank=True, null=True)
    bath_count = models.IntegerField(blank=True, null=True)
    bath_partial_count = models.PositiveSmallIntegerField(blank=True, null=True)
    bedrooms_count = models.PositiveSmallIntegerField(blank=True, null=True)
    rooms_count = models.PositiveSmallIntegerField(blank=True, null=True)
    stories_count = models.PositiveSmallIntegerField(blank=True, null=True)
    units_count = models.PositiveSmallIntegerField(blank=True, null=True)

    publication_date = models.DateField(blank=True, null=True)


class AttomAssessorDelete(models.Model):
    attom_id = models.PositiveIntegerField(primary_key=True)


class AttomLoan(models.Model):
    POSITION_OPEN_LOAN_TYPE_CHOICES = (
        (None, "Unknown"),
        ("P", "Purchase"),
        ("R", "Refinance"),
        ("E", "Equity"),
    )

    attom_id = models.OneToOneField(AttomAssessor, db_constraint=False, on_delete=models.CASCADE)

    # Jurisdiction
    situs_state_code = models.CharField(null=True, blank=True, max_length=2)
    situs_county = models.CharField(null=True, blank=True, max_length=50)
    property_jurisdiction_name = models.CharField(null=True, blank=True, max_length=50)
    situs_state_county_fips = models.CharField(null=True, blank=True, max_length=5)

    # Current first position
    cur_first_position_open_loan_amount = models.BigIntegerField(blank=True, null=True)
    cur_first_position_open_loan_document_number_formatted = models.CharField(
        null=True, blank=True, max_length=50)
    cur_first_position_open_loan_recording_date = models.DateField(blank=True, null=True)
    cur_first_position_open_loan_type = models.CharField(
        null=True, blank=True, max_length=1, choices=POSITION_OPEN_LOAN_TYPE_CHOICES)
    cur_first_position_open_loan_lender_name_first = models.CharField(
        null=True, blank=True, max_length=50)
    cur_first_position_open_loan_lender_name_last = models.CharField(
        null=True, blank=True, max_length=50)
    cur_first_position_open_loan_interest_rate_type = models.CharField(
        null=True, blank=True, max_length=3)
    cur_first_position_open_loan_interest_rate = models.DecimalField(
        max_digits=20, decimal_places=4, blank=True, null=True)
    cur_first_position_mortgage_type = models.CharField(null=True, blank=True, max_length=3)

    # Current second position
    cur_second_position_open_loan_amount = models.DecimalField(
        max_digits=20, decimal_places=4, blank=True, null=True)
    cur_second_position_open_loan_document_number_formatted = models.CharField(
        null=True, blank=True, max_length=50)
    cur_second_position_open_loan_recording_date = models.DateField(blank=True, null=True)
    cur_second_position_open_loan_type = models.CharField(
        null=True, blank=True, max_length=1, choices=POSITION_OPEN_LOAN_TYPE_CHOICES)
    cur_second_position_open_loan_lender_name_first = models.CharField(
        null=True, blank=True, max_length=50)
    cur_second_position_open_loan_lender_name_last = models.CharField(
        null=True, blank=True, max_length=50)
    cur_second_position_open_loan_lender_info_entity_class = models.CharField(
        null=True, blank=True, max_length=2)
    cur_second_position_open_loan_interest_rate_type = models.CharField(
        null=True, blank=True, max_length=3)
    cur_second_position_open_loan_interest_rate = models.DecimalField(
        max_digits=20, decimal_places=4, blank=True, null=True)
    cur_second_position_mortgage_type = models.CharField(null=True, blank=True, max_length=3)

    # Current third position
    cur_third_position_open_loan_transaction_id = models.PositiveIntegerField(blank=True, null=True)

    ltv = models.BigIntegerField(blank=True, null=True)
    available_equity = models.BigIntegerField(blank=True, null=True)
    lendable_equity = models.BigIntegerField(blank=True, null=True)

    publication_date = models.DateField(blank=True, null=True)


class AttomAmortizedLoanEquity(models.Model):
    attom_id = models.OneToOneField(AttomAssessor, db_constraint=False, on_delete=models.CASCADE)

    # Jurisdiction
    state = models.CharField(null=True, blank=True, max_length=2)
    county = models.CharField(null=True, blank=True, max_length=50)
    jurisdiction = models.CharField(null=True, blank=True, max_length=50)
    fips = models.CharField(null=True, blank=True, max_length=5)

    amortization_date = models.DateField(blank=True, null=True)

    first_loan_transaction_id = models.IntegerField(blank=True, null=True)
    first_loan_amortized = models.DecimalField(
        null=True, blank=True, decimal_places=4, max_digits=20)

    second_loan_transaction_id = models.IntegerField(blank=True, null=True)
    second_loan_amortized = models.DecimalField(
        null=True, blank=True, decimal_places=4, max_digits=20)

    third_loan_transaction_id = models.IntegerField(blank=True, null=True)
    third_loan_amortized = models.DecimalField(
        null=True, blank=True, decimal_places=4, max_digits=20)

    altv = models.PositiveSmallIntegerField(blank=True, null=True)

    est_avail_equity = models.PositiveIntegerField(blank=True, null=True)
    est_lendable_equity = models.PositiveIntegerField(blank=True, null=True)

    publication_date = models.DateField(blank=True, null=True)


class AttomPreForeclosure(models.Model):
    RECORD_TYPE_CHOICES = (
        (None, "Unknown or not provided"),
        ("LIS", "Lis Pendens"),
        ("NOD", "Notice of Default"),
        ("NOS", "Notice of Sale"),
        ("NTS", "Notice of Trustee's Sale"),
    )

    AREA_BUILDING_DEFINITION_CODE_CHOICES = (
        (None, "Unknown or not provided"),
        ("0", "Unknown"),
        ("10", "Living Area"),
        ("11", "Heated Area"),
        ("12", "Adjusted Area"),
        ("13", "Gross Area"),
        ("14", "Effective Area"),
        ("15", "Building Perimeter"),
        ("16", "Total Area"),
        ("17", "Base Area"),
        ("18", "Garage"),
        ("19", "Attic"),
        ("20", "Finished Area"),
    )

    transaction_id = models.PositiveIntegerField(primary_key=True)
    attom_id = models.ForeignKey(AttomAssessor, db_constraint=False, on_delete=models.CASCADE)
    record_type = models.CharField(null=True, blank=True, max_length=3, choices=RECORD_TYPE_CHOICES)
    situs_state_code = models.CharField(null=True, blank=True, max_length=2)
    situs_county = models.CharField(null=True, blank=True, max_length=50)

    # Size
    bath_count = models.PositiveSmallIntegerField(blank=True, null=True)
    bedrooms_count = models.PositiveSmallIntegerField(blank=True, null=True)
    area_building = models.PositiveIntegerField(blank=True, null=True)
    area_building_definition_code = models.CharField(
        null=True, blank=True, max_length=2, choices=AREA_BUILDING_DEFINITION_CODE_CHOICES)
    area_lot_sf = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    area_lot_acres = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)

    year_built = models.PositiveSmallIntegerField(blank=True, null=True)
    year_built_effective = models.PositiveSmallIntegerField(blank=True, null=True)

    # Loan details
    borrower_name_owner = models.CharField(null=True, blank=True, max_length=100)
    original_loan_loan_number = models.CharField(null=True, blank=True, max_length=25)
    original_loan_amount = models.DecimalField(
        max_digits=20, decimal_places=4, blank=True, null=True)
    original_loan_interest_rate = models.DecimalField(
        max_digits=20, decimal_places=4, blank=True, null=True)
    loan_maturity_date = models.DateField(blank=True, null=True)
    lender_name_full_standardized = models.CharField(null=True, blank=True, max_length=250)
    trustee_name = models.CharField(null=True, blank=True, max_length=150)

    # Foreclosure details
    foreclosure_recording_date = models.DateField(blank=True, null=True)
    default_amount = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    penalty_interest = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    loan_balance = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    judgment_date = models.DateField(blank=True, null=True)
    judgment_amount = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    auction_date = models.DateField(blank=True, null=True)
    auction_time = models.CharField(null=True, blank=True, max_length=20)
    estimated_value = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)

    create_date = models.DateField(blank=True, null=True)
    record_last_updated = models.DateField(blank=True, null=True)
    publication_date = models.DateField(blank=True, null=True)


class AttomRecorder(models.Model):
    MORTGAGE_TYPE_CHOICES = (
        (None, "UNKNOWN OR NOT PROVIDED"),
        ("0", "UNKNOWN"),
        ("3", "BUILDING OR CONSTRUCTION"),
        ("6", "LINE OF CREDIT"),
        ("8", "FHA"),
        ("10", "CONVENTIONAL"),
        ("11", "CONVENTIONAL WITH PMI"),
        ("16", "VETERANS ADMINISTRATION"),
        ("101", "USDA - US DEPT OF AGRICULTURE"),
        ("102", "FARMERS HOME ADMINISTRATION"),
        ("103", "COMMERCIAL"),
        ("104", "STATE VETERANS"),
        ("105", "REVERSE MORTGAGE"),
        ("121", "ASSUMPTION"),
        ("122", "BALLOON"),
        ("123", "ARM (ADJUSTABLE RATE MORTGAGE)"),
        ("124", "CLOSED END MORTGAGE"),
        ("125", "SELLER TAKE-BACK"),
        ("126", "STAND ALONE FIRST"),
        ("127", "STAND ALONE REFI"),
        ("128", "STAND ALONE SECOND"),
        ("129", "REFI-ASSIGNMENT"),
        ("130", "SECOND MORTGAGE TO COVER DOWN PYMT"),
        ("131", "LAND CONTRACT (ARGMT OF SALE)"),
        ("132", "LOAN MODIFICATION"),
        ("133", "SMALL BUSINESS ASSOC"),
        ("134", "CASH"),
        ("135", "NEGATIVE AMORTIZATION"),
    )

    transaction_id = models.PositiveIntegerField(primary_key=True)
    attom_id = models.ForeignKey(AttomAssessor, db_constraint=False, on_delete=models.CASCADE)

    recording_date = models.DateField(blank=True, null=True)
    quitclaim_flag = models.PositiveSmallIntegerField(blank=True, null=True)
    transfer_amount = models.DecimalField(max_digits=20, decimal_places=4, blank=True, null=True)
    transfer_amount_info_accuracy = models.CharField(null=True, blank=True, max_length=4)

    # Grantor
    grantor_1name_first = models.CharField(null=True, blank=True, max_length=50)
    grantor_1name_last = models.CharField(null=True, blank=True, max_length=50)
    grantor_2name_first = models.CharField(null=True, blank=True, max_length=50)
    grantor_2name_last = models.CharField(null=True, blank=True, max_length=50)

    # Grantee
    grantee_1name_first = models.CharField(null=True, blank=True, max_length=50)
    grantee_1name_last = models.CharField(null=True, blank=True, max_length=50)
    grantee_2name_first = models.CharField(null=True, blank=True, max_length=50)
    grantee_2name_last = models.CharField(null=True, blank=True, max_length=50)

    # Grantee mail address
    grantee_mail_address_full = models.CharField(null=True, blank=True, max_length=100)
    grantee_mail_address_house_number = models.CharField(null=True, blank=True, max_length=25)
    grantee_mail_address_street_direction = models.CharField(null=True, blank=True, max_length=10)
    grantee_mail_address_street_name = models.CharField(null=True, blank=True, max_length=100)
    grantee_mail_address_street_suffix = models.CharField(null=True, blank=True, max_length=25)
    grantee_mail_address_city = models.CharField(null=True, blank=True, max_length=50)
    grantee_mail_address_state = models.CharField(null=True, blank=True, max_length=2)
    grantee_mail_address_zip = models.CharField(null=True, blank=True, max_length=5)
    grantee_mail_address_zip4 = models.CharField(null=True, blank=True, max_length=4)

    # Mortage
    mortgage_1recording_date = models.DateField(blank=True, null=True)
    mortgage_1type = models.CharField(
        null=True, blank=True, max_length=3, choices=MORTGAGE_TYPE_CHOICES)
    mortgage_1amount = models.IntegerField(blank=True, null=True)
    mortgage_1lender_code = models.IntegerField(blank=True, null=True)
    mortgage_1lender_name_full_standardized = models.CharField(
        null=True, blank=True, max_length=250)

    # Transfer
    transfer_info_purchase_down_payment = models.IntegerField(blank=True, null=True)
    transfer_info_purchase_loan_to_value = models.DecimalField(
        max_digits=20, decimal_places=4, blank=True, null=True)

    last_updated = models.DateField(blank=True, null=True)
    publication_date = models.DateField(blank=True, null=True)
