package Carton::CLI::MediaWords;

use strict;
use warnings;

use Modern::Perl "2015";
use MediaWords::CommonLibs;

use Carton::Environment;
use parent( 'Carton::CLI' );

our $UseSystem = 0;    # 1 for unit testing

sub cmd_exec
{
    my ( $self, @args ) = @_;

    TRACE "cmd_exec override";

    my $env = Carton::Environment->build;
    $env->snapshot->load;

    # allows -Ilib
    @args = map { /^(-[I])(.+)/ ? ( $1, $2 ) : $_ } @args;

    while ( @args )
    {
        if ( $args[ 0 ] eq '-I' )
        {
            WARN "exec -Ilib is deprecated. You might want to run: carton exec perl -Ilib ...";
            splice( @args, 0, 2 );
        }
        else
        {
            last;
        }
    }

    my @include;
    $self->parse_options_pass_through( \@args );    # to handle --

    unless ( @args )
    {
        $self->error( "carton exec needs a command to run.\n" );
    }

    # PERL5LIB takes care of arch
    my $path = $env->install_path;
    my $lib = join ",", @include, "$path/lib/perl5", ".";

    my $carton_extra_perl5opt = $ENV{ CARTON_EXTRA_PERL5OPT } // '';

    TRACE "Extra PERL5OPT: $carton_extra_perl5opt";

    local $ENV{ PERL5OPT } = "-Mlib::core::only -Mlib=$lib $carton_extra_perl5opt";
    local $ENV{ PATH }     = "$path/bin:$ENV{PATH}";

    $UseSystem ? system( @args ) : exec( @args );
}

1;
