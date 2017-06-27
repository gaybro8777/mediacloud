package MediaWords::Util::Web::UserAgent::Response;

#
# Wrapper around HTTP::Response
#

use strict;
use warnings;

use Modern::Perl "2015";
use MediaWords::CommonLibs;

use MediaWords::Util::Web::UserAgent::Request;

use Data::Dumper;
use HTTP::Response;

sub new_from_http_response
{
    my ( $class, $response ) = @_;

    unless ( ref( $response ) eq 'HTTP::Response' )
    {
        LOGCONFESS "Response is not HTTP::Response: " . Dumper( $response );
    }

    my $self = {};
    bless $self, $class;

    $self->{ _response } = $response;

    if ( $response->request() )
    {
        $self->{ _request } = MediaWords::Util::Web::UserAgent::Request->new_from_http_request( $response->request() );
    }
    if ( $response->previous() )
    {
        $self->{ _previous } =
          MediaWords::Util::Web::UserAgent::Response->new_from_http_response( $response->previous() );
    }

    return $self;
}

# code() getter
sub code($)
{
    my ( $self ) = @_;
    return $self->{ _response }->code();
}

# message() getter
sub message($)
{
    my ( $self ) = @_;
    return $self->{ _response }->message();
}

# header() getter
sub header($$)
{
    my ( $self, $field ) = @_;
    return $self->{ _response }->header( $field );
}

# decoded_content() getter
sub decoded_content($)
{
    my ( $self ) = @_;
    return $self->{ _response }->decoded_content();
}

# decoded_content() getter with enforced UTF-8 response
sub decoded_utf8_content($)
{
    my ( $self ) = @_;
    return $self->{ _response }->decoded_content(
        charset         => 'utf8',
        default_charset => 'utf8'
    );
}

# status_line() getter
sub status_line($)
{
    my ( $self ) = @_;
    return $self->{ _response }->status_line();
}

# is_success() getter
sub is_success($)
{
    my ( $self ) = @_;
    return $self->{ _response }->is_success();
}

# Alias for as_string()
sub as_string($)
{
    my ( $self ) = @_;
    return $self->{ _response }->as_string();
}

# Alias for content_type()
sub content_type($)
{
    my ( $self ) = @_;
    return $self->{ _response }->content_type();
}

# previous() getter
sub previous($)
{
    my ( $self ) = @_;
    return $self->{ _previous };
}

# previous() setter
sub set_previous($$)
{
    my ( $self, $previous ) = @_;

    unless ( ref( $previous ) eq 'MediaWords::Util::Web::UserAgent::Response' )
    {
        LOGCONFESS "Previous response is not MediaWords::Util::Web::UserAgent::Response: " . Dumper( $previous );
    }
    $self->{ _previous } = $previous;
}

# request() getter
sub request($)
{
    my ( $self ) = @_;
    return $self->{ _request };
}

# request() setter
sub set_request($$)
{
    my ( $self, $request ) = @_;

    unless ( ref( $request ) eq 'MediaWords::Util::Web::UserAgent::Request' )
    {
        LOGCONFESS "Request is not MediaWords::Util::Web::UserAgent::Request: " . Dumper( $request );
    }
    $self->{ _request } = $request;
}

# Walk back from the given response to get the original request that generated the response.
sub original_request($)
{
    my ( $self ) = @_;

    my $original_response = $self;
    while ( $original_response->previous() )
    {
        $original_response = $original_response->previous();
    }

    return $original_response->request();
}

# Return true if the response's error was generated by LWP itself and not by the server.
sub error_is_client_side($)
{
    my ( $self ) = @_;

    if ( $self->is_success )
    {
        LOGCONFESS "Response was successful, but I have expected an error.";
    }

    my $header_client_warning = $self->header( 'Client-Warning' );
    if ( defined $header_client_warning and $header_client_warning =~ /Internal response/ )
    {
        # Error was generated by LWP::UserAgent;
        # likely we didn't reach server at all (timeout, unresponsive host,
        # etc.)
        #
        # http://search.cpan.org/~gaas/libwww-perl-6.05/lib/LWP/UserAgent.pm#$ua->get(_$url_)
        return 1;
    }
    else
    {
        return 0;
    }
}

1;
