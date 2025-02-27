"""Calandar platform for Teslemetry integration."""

from datetime import datetime, timedelta
from time import time
from itertools import chain
from typing import Any

from attr import dataclass
from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEvent,
)
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from tesla_fleet_api.const import Scope

from . import TeslemetryConfigEntry
from .entity import TeslemetryEnergyInfoEntity, TeslemetryVehicleEntity
from .models import TeslemetryEnergyData, TeslemetryVehicleData
from .helpers import handle_vehicle_command

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
            TeslemetryTariffSchedule(energy, "tariff_content_v2")
            for energy in entry.runtime_data.energysites
            if energy.info_coordinator.data.get("tariff_content_v2_seasons")
        ),(
            TeslemetryTariffSchedule(energy, "tariff_content_v2_sell_tariff")
            for energy in entry.runtime_data.energysites
            if energy.info_coordinator.data.get("tariff_content_v2_sell_tariff_seasons")
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

def parse_rrule(rrule: str) -> dict[str,str]:
    """Parse an rrule string into a dictionary of configurations."""
    return dict(s.split("=") for s in rrule.split(";"))

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

    name: str
    startMins: timedelta
    endMins: timedelta
    days_of_week: int
    uid: str
    location: str
    rrule: str | None


class TeslemetryChargeSchedule(TeslemetryVehicleEntity, CalendarEntity):
    """Vehicle Charge Schedule Calendar."""

    _attr_supported_features = CalendarEntityFeature(
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )
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
                            summary=schedule.name,
                            description=schedule.location,
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
            day = dt_util.start_of_local_day()
            count = 0

            while day < end_date and (count < 7 or schedule.rrule):
                if day >= start_date and test_days_of_week(day, schedule.days_of_week):
                    start = day + schedule.startMins
                    end = day + schedule.endMins
                    if (end > start_date) and (start < end_date):
                        events.append(
                            CalendarEvent(
                                start=start,
                                end=end,
                                summary=schedule.name,
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
            if not schedule["enabled"] or not schedule["days_of_week"]:
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

            rrule = f"FREQ=WEEKLY;WKST=MO;BYDAY={','.join(get_rrule_days(schedule['days_of_week']))}"
            if schedule["one_time"]:
                rrule += ";COUNT=1"


            self.schedules.append(
                Schedule(
                    name=schedule["name"] or self.summary,
                    startMins=startMins,
                    endMins=endMins,
                    days_of_week=schedule["days_of_week"],
                    uid=str(schedule["id"]),
                    location=f"{schedule['latitude']},{schedule['longitude']}",
                    rrule=rrule
                )
            )

    async def _change(self, event: dict[str,Any]):
        """Add or update an event on the calendar."""

        if "dtend" not in event and "dtstart" not in event:
            raise ServiceValidationError("Missing start or end")
        if "description" in event and event["description"]:
            try:
                latitude, longitude = event["description"].split(",")
                latitude = float(latitude)
                longitude = float(longitude)
            except ValueError:
                raise ServiceValidationError("Description must be a comma separated latitude and longitude, or left blank")
        elif self.hass.config.latitude and self.hass.config.longitude:
            latitude = self.hass.config.latitude
            longitude = self.hass.config.longitude
        else:
            raise ServiceValidationError("Missing location")
        if "rrule" in event:
            one_time = False
            rrule = parse_rrule(event["rrule"])

            if "INTERVAL" in rrule and rrule["INTERVAL"] != 1:
                raise ServiceValidationError("Repeat interval must be 1 week")
            if "UNTIL" in rrule or ("COUNT" in rrule and rrule["COUNT"] == 1):
                raise ServiceValidationError("End must be Never or 1")
            if rrule["FREQ"]=="DAILY" in rrule:
                days_of_week = "All"
            else:
                if rrule["FREQ"]!="WEEKLY":
                    raise ServiceValidationError("Repeat must be daily or weekly")
                if "BYDAY" not in rrule:
                    raise ServiceValidationError("Missing days of week")
                days_of_week = ",".join([RRULE_DAYS[day] for day in rrule["BYDAY"].split(",")])
        else:
            days_of_week = DAYS[event["dtend"].weekday()]
            one_time = True

        start_time = event["dtstart"].hour * 60 + event["dtstart"].minute if "dtstart" in event else None
        end_time = event["dtend"].hour * 60 + event["dtend"].minute if "dtend" in event else None

        await handle_vehicle_command(self.api.add_charge_schedule(
            id=event.get("id"),
            name=event.get("name",self.summary),
            days_of_week=days_of_week,
            enabled=True,
            lat=latitude,
            lon=longitude,
            start_time=start_time,
            end_time=end_time,
            one_time=one_time
        ))
        self.coordinator.data["preconditioning_schedule_data_precondition_schedules"].append({
            "id": id,
            "name": event.get("name"),
            "days_of_week": days_of_week,
            "enabled": True,
            "lat": latitude,
            "lon": longitude,
            "start_enabled": bool(start_time),
            "start_time": start_time,
            "end_enabled": bool(end_time),
            "end_time": end_time,
            "one_time": one_time
        })
        self.async_write_ha_state()

    async def async_create_event(self, **kwargs: Any) -> None:
        """Add a new event to calendar."""
        await self._change(kwargs)

    async def async_update_event(
            self,
            uid: str,
            event: dict[str, Any],
            recurrence_id: str | None = None,
            recurrence_range: str | None = None,
        ) -> None:
        """Update an event on the calendar."""

        event["id"] = int(uid)
        await self._change(event)

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event on the calendar."""
        id = int(uid)
        await handle_vehicle_command(self.api.remove_charge_schedule(id))
        self.coordinator.data["preconditioning_schedule_data_precondition_schedules"] = [
            s for s in self.coordinator.data["preconditioning_schedule_data_precondition_schedules"] if s["id"] != id
        ]
        self.async_write_ha_state()

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
                                summary=schedule.name,
                                description=schedule.location,
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
            day = dt_util.start_of_local_day()
            count = 0

            while day < end_date and (count < 7 or schedule.rrule):
                if day >= start_date and test_days_of_week(day, schedule.days_of_week):
                    start = day + schedule.startMins
                    end = day + schedule.endMins
                    if (end > start_date) and (start < end_date):
                        events.append(
                            CalendarEvent(
                                start=start,
                                end=end,
                                summary=schedule.name,
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
            if not schedule["enabled"] or not schedule["days_of_week"]:
                continue
            startMins = timedelta(minutes=schedule["precondition_time"])
            endMins = timedelta(minutes=schedule["precondition_time"])

            rrule = None
            if not schedule["one_time"]:
                rrule = f"FREQ=WEEKLY;WKST=MO;BYDAY={','.join(get_rrule_days(schedule['days_of_week']))}"

            self.schedules.append(
                Schedule(
                    name=schedule["name"] or self.summary,
                    startMins=startMins,
                    endMins=endMins,
                    days_of_week=schedule["days_of_week"],
                    uid=str(schedule["id"]),
                    location=f"{schedule['latitude']},{schedule['longitude']}",
                    rrule=rrule,

                )
            )

    async def _change(self, event) -> None:
        """Add or change a schedule."""

        if "dtend" not in event:
            raise ServiceValidationError("Missing start or end")
        if "description" in event and event["description"]:
            try:
                latitude, longitude = event["description"].split(",")
                latitude = float(latitude)
                longitude = float(longitude)
            except ValueError:
                raise ServiceValidationError("Description must be a comma separated latitude and longitude, or left blank")
        elif self.hass.config.latitude and self.hass.config.longitude:
            latitude = self.hass.config.latitude
            longitude = self.hass.config.longitude
        else:
            raise ServiceValidationError("Missing location")
        if "rrule" in event:
            one_time = False
            rrule_str = event["rrule"]
            if "INTERVAL=" in rrule_str and "INTERVAL=1" not in rrule_str:
                raise ServiceValidationError("Repeat interval must be 1 week")
            if "UNTIL=" in rrule_str or ("COUNT=" in rrule_str and "COUNT=1" not in rrule_str):
                raise ServiceValidationError("End must be Never or 1")
            if "FREQ=DAILY" in rrule_str:
                days_of_week = "All"
            else:
                if "FREQ=WEEKLY" not in rrule_str:
                    raise ServiceValidationError("Repeat must be daily or weekly")
                if "BYDAY=" not in rrule_str:
                    raise ServiceValidationError("Missing days of week")
                days_of_week = ",".join([RRULE_DAYS[day] for day in rrule_str.split("BYDAY=")[1].split(";")[0].split(",")])
        else:
            days_of_week = DAYS[event["dtend"].weekday()]
            one_time = True

        id = event.get("id",int(time()))
        await handle_vehicle_command(self.api.add_precondition_schedule(
            id=id,
            days_of_week=days_of_week,
            enabled=True,
            lat=latitude,
            lon=longitude,
            precondition_time=event["dtend"].hour * 60 + event["dtend"].minute,
            one_time=one_time
        ))
        self.coordinator.data["preconditioning_schedule_data_precondition_schedules"].append({
            "id": id,
            "name": event.get("name"),
            "days_of_week": days_of_week,
            "enabled": True,
            "lat": latitude,
            "lon": longitude,
            "precondition_time": event["dtend"].hour * 60 + event["dtend"].minute,
            "one_time": one_time
        })
        self.async_write_ha_state()

    async def async_create_event(self, **kwargs: Any) -> None:
        """Add a new event to calendar."""
        await self._change(kwargs)

    async def async_update_event(
            self,
            uid: str,
            event: dict[str, Any],
            recurrence_id: str | None = None,
            recurrence_range: str | None = None,
        ) -> None:
        """Update an event on the calendar."""

        event["id"] = int(uid)
        await self._change(event)

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event on the calendar."""
        id = int(uid)
        await handle_vehicle_command(self.api.remove_precondition_schedule(id))
        self.coordinator.data["preconditioning_schedule_data_precondition_schedules"] = [
            schedule for schedule in self.coordinator.data["preconditioning_schedule_data_precondition_schedules"] if schedule["id"] != id
        ]
        self.async_write_ha_state()

@dataclass
class TarrifPeriod:
    """A single tariff period."""

    name: str
    price: float
    fromHour: int = 0
    fromMinute: int = 0
    toHour: int = 0
    toMinute: int = 0

class TeslemetryTariffSchedule(TeslemetryEnergyInfoEntity, CalendarEntity):
    """Vehicle Charge Schedule Calendar."""

    seasons: dict[str, dict[str, Any]]
    charges: dict[str, dict[str, Any]]
    currency: str

    def __init__(
        self,
        data: TeslemetryEnergyData,
        key: str,
    ) -> None:
        """Initialize the climate."""
        super().__init__(data, key)


    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""

        for season in self.seasons:
            if not self.seasons[season]:
                continue
            now = dt_util.now()
            start = datetime(now.year, self.seasons[season]["fromMonth"], self.seasons[season]["fromDay"], tzinfo=now.tzinfo)
            end = datetime(now.year, self.seasons[season]["toMonth"], self.seasons[season]["toDay"], tzinfo=now.tzinfo) + timedelta(days=1)
            if end <= now or start >= now:
                continue
            for name in self.seasons[season]["tou_periods"]:
                for period in self.seasons[season]["tou_periods"][name]["periods"]:
                    day = now.weekday()
                    if day < period.get("fromDayOfWeek",0) or day > period.get("toDayOfWeek",6):
                        continue
                    start_time = datetime(now.year, now.month, now.day, period.get("fromHour",0) % 24, period.get("fromMinute",0) % 60, tzinfo=now.tzinfo)
                    end_time = datetime(now.year, now.month, now.day, period.get("toHour",0) % 24, period.get("toMinute",0) % 60, tzinfo=now.tzinfo)
                    if end_time < start_time:
                        end_time += timedelta(days=1)
                    if end_time > now and start_time < now:
                        price = self.charges.get(season, self.charges["ALL"])["rates"].get(name,self.charges["ALL"]["rates"]["ALL"])
                        return CalendarEvent(
                            start=start_time,
                            end=end_time,
                            summary=f"{price}/kWh",
                            description=f"Seasons: {season}\nPeriod: {name}\nPrice: {price}/kWh",
                        )
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        events: list[CalendarEvent] = []

        TZ = dt_util.get_default_time_zone()

        for year in range(start_date.year, end_date.year + 1):
            for season in self.seasons:
                if not self.seasons[season]:
                    continue
                start = datetime(year, self.seasons[season]["fromMonth"], self.seasons[season]["fromDay"], tzinfo=TZ)
                end = datetime(year, self.seasons[season]["toMonth"], self.seasons[season]["toDay"], tzinfo=TZ) + timedelta(days=1)

                if end <= start_date or start >= end_date:
                    continue

                week: list[list[TarrifPeriod]] = [[],[],[],[],[],[],[]]
                for name in self.seasons[season]["tou_periods"]:
                    for period in self.seasons[season]["tou_periods"][name]["periods"]:
                        for day in range(period.get("fromDayOfWeek",0),period.get("toDayOfWeek",6)+1):
                            week[day].append(TarrifPeriod(
                                name,
                                self.charges.get(season, self.charges["ALL"])["rates"].get(name,self.charges["ALL"]["rates"]["ALL"]),
                                period.get("fromHour",0) % 24,
                                period.get("fromMinute",0) % 60,
                                period.get("toHour",0) % 24,
                                period.get("toMinute",0) % 60
                            ))

                start = max(start_date, start)
                end = min(end_date, end)

                day = start
                while day < end:
                    weekday = day.weekday()
                    for period in week[weekday]:
                        start_time = datetime(day.year, day.month, day.day, period.fromHour, period.fromMinute, tzinfo=TZ)
                        end_time = datetime(day.year, day.month, day.day, period.toHour, period.toMinute, tzinfo=TZ)
                        if end_time < start_time:
                            end_time += timedelta(days=1)
                        if end_time > start_date or start_time < end_date:
                            events.append(
                                CalendarEvent(
                                    start=start_time,
                                    end=end_time,
                                    summary=f"{period.price}/kWh",
                                    description=f"Seasons: {season}\nPeriod: {period.name}\nPrice: {period.price}/kWh",
                                )
                            )
                    day += timedelta(days=1)
        return events



    def _async_update_attrs(self) -> None:
        """Update the calandar events."""
        seasons = self.get(f"{self.key}_seasons")
        assert seasons
        self.seasons = seasons
        charges = self.get(f"{self.key}_energy_charges")
        assert charges
        self.charges = charges
