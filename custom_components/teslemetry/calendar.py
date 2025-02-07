"""Calandar platform for Teslemetry integration."""

from typing import Any, cast
from itertools import chain
from datetime import datetime, timedelta
from dateutil.rrule import rrulestr

from attr import dataclass
from tesla_fleet_api.const import Scope, CabinOverheatProtectionTemp
from teslemetry_stream import Signal

from homeassistant.components.calendar import (
    CalendarEvent,
    CalendarEntity,
)
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from voluptuous.validators import Number

from . import TeslemetryConfigEntry
from .const import LOGGER, TeslemetryClimateSide, DOMAIN
from .entity import TeslemetryEnergyInfoEntity, TeslemetryVehicleComplexStreamEntity, TeslemetryVehicleEntity
from .models import TeslemetryEnergyData, TeslemetryVehicleData

RRULE_DAYS = {
    "MO": "Monday",
    "TU": "Tuesday",
    "WE": "Wednesday",
    "TH": "Thursday",
    "FR": "Friday",
    "SA": "Saturday",
    "SU": "Sunday",
}
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

async def async_setup_entry(
    hass: HomeAssistant, entry: TeslemetryConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Teslemetry Calander platform from a config entry."""

    async_add_entities(
        chain((
            TeslemetryChargeSchedule(
                vehicle, entry.runtime_data.scopes
            )
            for vehicle in entry.runtime_data.vehicles
        ),(
            TeslemetryPreconditionSchedule(
                vehicle, entry.runtime_data.scopes
            )
            for vehicle in entry.runtime_data.vehicles
        ),(
            TeslemetryTariffSchedule(energy)
            for energy in entry.runtime_data.energysites
            if energy.info_coordinator.data.get("tariff_content")
        ))
    )

def get_rrule_days(days_of_week: int) -> list[str]:
    """Get the rrule days for a days_of_week binary."""

    rrule_days = []
    if days_of_week & 0b0000001:
        rrule_days.append("MO")
    if days_of_week & 0b0000010:
        rrule_days.append("TU")
    if days_of_week & 0b0000100:
        rrule_days.append("WE")
    if days_of_week & 0b0001000:
        rrule_days.append("TH")
    if days_of_week & 0b0010000:
        rrule_days.append("FR")
    if days_of_week & 0b0100000:
        rrule_days.append("SA")
    if days_of_week & 0b1000000:
        rrule_days.append("SU")
    return rrule_days

def test_days_of_week(date: datetime, test_days_of_week: int) -> bool:
    """Check if a specific day is in the days_of_week binary."""
    return test_days_of_week & 1 << date.weekday() > 0

def get_delta(minutes: int, days_of_week: int, start: datetime) -> timedelta:
    """Figure out how far in the future the schedule is."""

    startDay = start.weekday()
    startMinutes = start.hour * 60 + start.minute
    for i in range(7):
        if days_of_week & 1 << ((startDay + i) % 7) and (i or startMinutes < minutes):
            return timedelta(days=i, minutes=minutes-startMinutes)
    raise ValueError("Schedule has no days")

@dataclass
class Schedule:
    """A schedule for a vehicle."""

    startMins: timedelta
    endMins: timedelta
    days_of_week: int
    uid: str
    location: str
    rrule: str | None


class TeslemetryChargeSchedule(TeslemetryVehicleEntity, CalendarEntity):
    """Vehicle Charge Schedule Calendar."""

    _attr_supported_features = CalendarEntityFeature(0)
    #(
    #    CalendarEntityFeature.CREATE_EVENT
    #    | CalendarEntityFeature.DELETE_EVENT
    #    | CalendarEntityFeature.UPDATE_EVENT
    #)
    schedules: list[Schedule] = []
    summary: str

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the climate."""
        self.summary = f"Charge scheduled for {data.device.get('name')}"
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CalendarEntityFeature(0)
        super().__init__(data, "charge_schedule_data_charge_schedules")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        now = dt_util.now()
        event = None
        for schedule in self.schedules:
            day = dt_util.start_of_local_day()
            while not event or day < event.start:
                if test_days_of_week(day, schedule.days_of_week):
                    start = day + schedule.startMins
                    end = day + schedule.endMins

                    if (end > now and (not event or start < event.start)):
                        event = CalendarEvent(
                                start=start,
                                end=end,
                                summary=self.summary,
                                location=schedule.location,
                                uid=schedule.uid,
                                rrule=schedule.rrule
                            )
                day += timedelta(days=1)
        return event

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""

        events = []
        for schedule in self.schedules:
            day = dt_util.start_of_local_day(start_date)
            count = 0

            while day < end_date and (count < 7 or schedule.rrule):
                if test_days_of_week(day, schedule.days_of_week):
                    start = day + schedule.startMins
                    end = day + schedule.endMins
                    if (end > start_date) and (start < end_date):
                        events.append(
                            CalendarEvent(
                                start=start,
                                end=end,
                                summary=self.summary,
                                location=schedule.location,
                                uid=schedule.uid,
                                rrule=schedule.rrule
                            )
                        )
                day += timedelta(days=1)
                count += 1
        return events


    def _async_update_attrs(self) -> None:
        """Update the calandar events."""
        schedules = self._value or []
        self.schedules = []
        for schedule in schedules:
            if not schedule["enabled"]:
                continue
            if not schedule["end_enabled"]:
                startMins = timedelta(minutes=schedule["start_time"])
                endMins = startMins
            elif not schedule["start_enabled"]:
                endMins = timedelta(minutes=schedule["end_time"])
                startMins = endMins
            elif schedule["start_time"] > schedule["end_time"]:
                startMins = timedelta(minutes=schedule["start_time"])
                endMins = timedelta(days=1,minutes=schedule["end_time"])
            else:
                startMins = timedelta(minutes=schedule["start_time"])
                endMins = timedelta(minutes=schedule["end_time"])

            rrule = None
            if not schedule["one_time"]:
                rrule = f"FREQ=WEEKLY;WKST=MO;BYDAY={','.join(get_rrule_days(schedule['days_of_week']))}"

            self.schedules.append(
                Schedule(
                    startMins=startMins,
                    endMins=endMins,
                    days_of_week=schedule["days_of_week"],
                    uid=str(schedule["id"]),
                    location=f"{schedule['latitude']},{schedule['longitude']}",
                    rrule=rrule
                )
            )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event on the calendar."""
        self.api.remove_charge_schedule(int(uid))


class TeslemetryPreconditionSchedule(TeslemetryVehicleEntity, CalendarEntity):
    """Vehicle Precondition Schedule Calendar."""

    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )
    events: list[CalendarEvent]
    summary: str

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the climate."""
        self.summary = f"Precondition scheduled for {data.device.get('name')}"
        self.scoped = Scope.VEHICLE_CMDS in scopes
        if not self.scoped:
            self._attr_supported_features = CalendarEntityFeature(0)
        super().__init__(data, "preconditioning_schedule_data_precondition_schedules")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        now = dt_util.now()
        event = None
        for schedule in self.schedules:
            day = dt_util.start_of_local_day()
            while not event or day < event.start:
                if test_days_of_week(day, schedule.days_of_week):
                    start = day + schedule.startMins
                    end = day + schedule.endMins

                    if (end > now and (not event or start < event.start)):
                        event = CalendarEvent(
                                start=start,
                                end=end,
                                summary=self.summary,
                                location=schedule.location,
                                uid=schedule.uid,
                                rrule=schedule.rrule
                            )
                day += timedelta(days=1)
        return event

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""

        events = []
        for schedule in self.schedules:
            day = dt_util.start_of_local_day(max(start_date, dt_util.now()))
            count = 0

            while day < end_date and (count < 7 or schedule.rrule):
                if test_days_of_week(day, schedule.days_of_week):
                    start = day + schedule.startMins
                    end = day + schedule.endMins
                    if (end > start_date) and (start < end_date):
                        events.append(
                            CalendarEvent(
                                start=start,
                                end=end,
                                summary=self.summary,
                                description=schedule.location,
                                location=schedule.location,
                                uid=schedule.uid,
                                rrule=schedule.rrule
                            )
                        )
                day += timedelta(days=1)
                count += 1
        return events


    def _async_update_attrs(self) -> None:
        """Update the calandar events."""
        schedules = self._value or []
        self.schedules = []
        for schedule in schedules:
            if not schedule["enabled"]:
                continue
            startMins = timedelta(minutes=schedule["precondition_time"])
            endMins = timedelta(minutes=schedule["precondition_time"])

            rrule = None
            if not schedule["one_time"]:
                rrule = f"FREQ=WEEKLY;WKST=MO;BYDAY={','.join(get_rrule_days(schedule['days_of_week']))}"

            self.schedules.append(
                Schedule(
                    startMins=startMins,
                    endMins=endMins,
                    days_of_week=schedule["days_of_week"],
                    uid=str(schedule["id"]),
                    location=f"{schedule['latitude']},{schedule['longitude']}",
                    rrule=rrule
                )
            )

    async def async_create_event(self, **kwargs: Any) -> None:
        """Add a new event to calendar."""
        print(kwargs)
        if "dtend" not in kwargs:
            raise ServiceValidationError("Missing start or end")
        if "description" in kwargs and kwargs["description"]:
            try:
                latitude, longitude = kwargs["location"].split(",")
                latitude = float(latitude)
                longitude = float(longitude)
            except ValueError:
                raise ServiceValidationError("Location must be a comma separated latitude and longitude")
        elif self.hass.config.latitude and self.hass.config.longitude:
            latitude = self.hass.config.latitude
            longitude = self.hass.config.longitude
        else:
            raise ServiceValidationError("Missing location")
        if "rrule" in kwargs:
            one_time = False
            rrule_str = kwargs["rrule"]
            print(rrule_str)
            if "FREQ=WEEKLY" not in rrule_str:
                raise ServiceValidationError("Repeat must be weekly")
            if "INTERVAL=" in rrule_str and "INTERVAL=1" not in rrule_str:
                raise ServiceValidationError("Repeat interval must be 1 week")
            if "UNTIL=" in rrule_str or "COUNT=" in rrule_str:
                raise ServiceValidationError("End must be Never")
            if "BYDAY=" not in rrule_str:
                raise ServiceValidationError("Missing days of week")
            byday = rrule_str.split("BYDAY=")[1].split(";")[0].split(",")
            days_of_week = ",".join([RRULE_DAYS[day] for day in byday])
            one_time = False
        else:
            days_of_week = DAYS[kwargs["dtend"].weekday()]
            one_time = True

        print(days_of_week,latitude,longitude,kwargs["dtend"].hour * 60 + kwargs["dtend"].minute,one_time)

        await self.api.add_precondition_schedule(
            days_of_week=days_of_week,
            enabled=True,
            lat=latitude,
            lon=longitude,
            precondition_time=kwargs["dtend"].hour * 60 + kwargs["dtend"].minute,
            one_time=one_time
        )

    async def async_update_event(
            self,
            uid: str,
            event: dict[str, Any],
            recurrence_id: str | None = None,
            recurrence_range: str | None = None,
        ) -> None:
            """Update an event on the calendar."""

            try:
                latitude, longitude = kwargs["location"].split(",")
                latitude = float(latitude)
                longitude = float(longitude)
            except ValueError:
                raise ServiceValidationError("Location must be a comma separated latitude and longitude")
            #if "rrule" in kwargs:

            await self.api.add_precondition_schedule(
                id=int(uid),
                days_of_week="Monday",
                enabled=True,
                lat=latitude,
                lon=longitude,
                precondition_time=event["end"].hour * 60 + event["end"].minute,
            )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event on the calendar."""
        await self.api.remove_precondition_schedule(int(uid))

class TeslemetryTariffSchedule(TeslemetryEnergyInfoEntity, CalendarEntity):
    """Vehicle Charge Schedule Calendar."""

    def __init__(
        self,
        data: TeslemetryEnergyData
    ) -> None:
        """Initialize the climate."""
        super().__init__(data, "tariff_content_v2")
        assert self._value
        self._attr_name = f"{self._value.get('utility')} {self._value.get('name')}"


    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        events: list[CalendarEvent] = []
        tarrifs = self._value or {}
        seasons = tarrifs.get("seasons", {})
        energy_charges = tarrifs.get("energy_charges", {})
        TZ = dt_util.get_default_time_zone()

        for year in range(start_date.year, end_date.year + 1):
            print(year)
            for season in seasons:
                if not seasons[season]:
                    continue
                print(season)
                start = datetime(year, seasons[season]["fromMonth"], seasons[season]["fromDay"], tzinfo=TZ)
                end = datetime(year, seasons[season]["toMonth"], seasons[season]["toDay"], tzinfo=TZ) + timedelta(days=1)

                if end <= start_date or start >= end_date:
                    continue

                week: list[list[dict[str,str|int]]] = [[],[],[],[],[],[],[]]
                for name in seasons[season]["tou_periods"]:
                    print(name)
                    for period in seasons[season]["tou_periods"][name]["periods"]:
                        print(period)
                        for day in range(period.get("fromDayOfWeek",0),period.get("toDayOfWeek",6)+1):
                            print(day)
                            week[day].append({
                                "name": name,
                                "from": period.get("fromHour",0),
                                "to": period.get("toHour",23),
                                "price": energy_charges.get(season, energy_charges["ALL"])["rates"].get(name,energy_charges["ALL"]["rates"]["ALL"])
                            })

                start = max(start_date, start)
                end = min(end_date, end)

                print(week)

                day = start
                while day < end:
                    weekday = day.weekday()
                    for period in week[weekday]:
                        start_time = datetime(day.year, day.month, day.day, period["from"], tzinfo=TZ)
                        end_time = datetime(day.year, day.month, day.day, period["to"], tzinfo=TZ)
                        if period["to"] < period["from"]:
                            end_time += timedelta(days=1)
                        if end_time > start_date or start_time < end_date:
                            events.append(
                                CalendarEvent(
                                    start=start_time,
                                    end=end_time,
                                    summary=period['name'],
                                    description=f"Seasons: {season}\nPrice: {period["price"]}/kWh",
                                )
                            )
                    day += timedelta(days=1)
        return events



    def _async_update_attrs(self) -> None:
        """Update the calandar events."""
        pass
