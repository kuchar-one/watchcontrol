package nodomain.freeyourgadget.gadgetbridge.devices.yawell.ring;

import android.os.Parcel;
import android.text.InputType;

import androidx.preference.Preference;

import java.util.Collections;
import java.util.Set;

import nodomain.freeyourgadget.gadgetbridge.GBApplication;
import nodomain.freeyourgadget.gadgetbridge.activities.devicesettings.DeviceSpecificSettingsCustomizer;
import nodomain.freeyourgadget.gadgetbridge.activities.devicesettings.DeviceSpecificSettingsHandler;
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice;
import nodomain.freeyourgadget.gadgetbridge.model.NotificationSpec;
import nodomain.freeyourgadget.gadgetbridge.model.NotificationType;
import nodomain.freeyourgadget.gadgetbridge.util.Prefs;

public class YawellRingSettingsCustomizer implements DeviceSpecificSettingsCustomizer {
    private final GBDevice device;

    public YawellRingSettingsCustomizer(final GBDevice device) {
        this.device = device;
    }

    @Override
    public void onPreferenceChange(final Preference preference, final DeviceSpecificSettingsHandler handler) {
    }

    @Override
    public void customizeSettings(final DeviceSpecificSettingsHandler handler, final Prefs prefs, final String rootKey) {
        for (final NotificationType type : NotificationType.values()) {
            String countPrefKey = "mi_vibration_count_" + type.getGenericType();
            handler.setInputTypeFor(countPrefKey, InputType.TYPE_CLASS_NUMBER);
            String tryPrefKey = "mi_try_" + type.getGenericType();
            final Preference tryPref = handler.findPreference(tryPrefKey);
            if (tryPref != null) {
                tryPref.setOnPreferenceClickListener(preference -> {
                    tryVibration(type);
                    return true;
                });
            }
        }
    }

    private void tryVibration(NotificationType type) {
        NotificationSpec spec = new NotificationSpec();
        spec.type = type;
        GBApplication.deviceService(device).onNotification(spec);
    }

    @Override
    public Set<String> getPreferenceKeysWithSummary() {
        return Collections.emptySet();
    }

    public static final Creator<YawellRingSettingsCustomizer> CREATOR = new Creator<YawellRingSettingsCustomizer>() {
        @Override
        public YawellRingSettingsCustomizer createFromParcel(final Parcel in) {
            final GBDevice device = in.readParcelable(YawellRingSettingsCustomizer.class.getClassLoader());
            return new YawellRingSettingsCustomizer(device);
        }

        @Override
        public YawellRingSettingsCustomizer[] newArray(final int size) {
            return new YawellRingSettingsCustomizer[size];
        }
    };

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(final Parcel dest, final int flags) {
        dest.writeParcelable(device, 0);
    }
}
